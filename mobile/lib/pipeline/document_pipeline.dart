/// Document intelligence pipeline for ETHIO.
///
/// Stages: validate -> extract -> detect conflicts -> confirm.
///
/// Safety rules enforced here (in code, not comments):
/// * [RawExtraction] is UNTRUSTED machine output. [ConfirmedField] is data a
///   human has explicitly verified. They are different types with no implicit
///   conversion — raw OCR output can never be mistaken for confirmed data.
/// * When two sources disagree on an identity field, the pipeline surfaces
///   an [IssueItem] conflict and NEVER auto-resolves it. Resolution happens
///   only through an explicit user choice.
/// * No real OCR provider is used: [MockOcrExtractor] is a clearly-labeled
///   simulator. It makes no network calls.
library;

import '../models/task.dart';

// ---------------------------------------------------------------------------
// File validation
// ---------------------------------------------------------------------------

/// Maximum accepted upload size: 10 MB.
const int maxDocumentBytes = 10 * 1024 * 1024;

/// MIME types the pipeline accepts.
const Set<String> allowedMimeTypes = {
  'application/pdf',
  'image/jpeg',
  'image/png',
};

/// Fallback MIME lookup by file extension, used when no MIME type is given.
const Map<String, String> _mimeByExtension = {
  'pdf': 'application/pdf',
  'jpg': 'image/jpeg',
  'jpeg': 'image/jpeg',
  'png': 'image/png',
};

/// Why a document was rejected.
enum DocumentErrorKind {
  /// File type is not PDF/JPG/PNG.
  unsupportedType,

  /// File is larger than [maxDocumentBytes].
  tooLarge,

  /// File has no content.
  emptyFile,

  /// Content does not match the claimed type (magic-byte sniff).
  malformed,
}

/// Typed validation failure. Catch this (not a generic Exception) to tell
/// the user exactly what went wrong with their file.
class DocumentValidationError implements Exception {
  const DocumentValidationError({
    required this.kind,
    required this.fileName,
    required this.message,
  });

  final DocumentErrorKind kind;
  final String fileName;
  final String message;

  @override
  String toString() => 'DocumentValidationError($kind, $fileName): $message';
}

/// A file handed to the pipeline. [bytes] is optional: when present, the
/// pipeline also sniffs the content's magic bytes.
class DocumentFile {
  const DocumentFile({
    required this.fileName,
    required this.mimeType,
    required this.sizeBytes,
    this.bytes,
  });

  final String fileName;

  /// Claimed MIME type; may be empty if unknown (extension is used instead).
  final String mimeType;
  final int sizeBytes;
  final List<int>? bytes;

  /// Effective MIME type: the claimed one, or the extension fallback.
  String get effectiveMimeType {
    if (mimeType.trim().isNotEmpty) return mimeType.trim().toLowerCase();
    final dot = fileName.lastIndexOf('.');
    if (dot < 0) return '';
    final ext = fileName.substring(dot + 1).toLowerCase();
    return _mimeByExtension[ext] ?? '';
  }
}

/// Validate a file. Returns normally when the file is acceptable; throws a
/// typed [DocumentValidationError] otherwise.
void validateDocument(DocumentFile file) {
  final mime = file.effectiveMimeType;
  if (!allowedMimeTypes.contains(mime)) {
    throw DocumentValidationError(
      kind: DocumentErrorKind.unsupportedType,
      fileName: file.fileName,
      message:
          'Type "$mime" is not supported. Please upload a PDF, JPG or PNG file.',
    );
  }
  if (file.sizeBytes <= 0) {
    throw DocumentValidationError(
      kind: DocumentErrorKind.emptyFile,
      fileName: file.fileName,
      message: 'The file is empty. Please choose a file with content.',
    );
  }
  if (file.sizeBytes > maxDocumentBytes) {
    throw DocumentValidationError(
      kind: DocumentErrorKind.tooLarge,
      fileName: file.fileName,
      message:
          'The file is ${(file.sizeBytes / (1024 * 1024)).toStringAsFixed(1)} MB; '
          'the limit is ${maxDocumentBytes ~/ (1024 * 1024)} MB.',
    );
  }
  final bytes = file.bytes;
  if (bytes != null && bytes.isNotEmpty && !_magicMatches(mime, bytes)) {
    throw DocumentValidationError(
      kind: DocumentErrorKind.malformed,
      fileName: file.fileName,
      message:
          'The file content does not look like a $mime file. It may be corrupt.',
    );
  }
}

/// Non-throwing variant: returns the list of problems (empty = valid).
List<DocumentValidationError> tryValidate(DocumentFile file) {
  try {
    validateDocument(file);
    return const [];
  } on DocumentValidationError catch (e) {
    return [e];
  }
}

/// Light magic-byte sniff: PDF starts with "%PDF", JPEG with FF D8,
/// PNG with 89 50 4E 47.
bool _magicMatches(String mime, List<int> bytes) {
  bool startsWith(List<int> sig) {
    if (bytes.length < sig.length) return false;
    for (var i = 0; i < sig.length; i++) {
      if (bytes[i] != sig[i]) return false;
    }
    return true;
  }

  switch (mime) {
    case 'application/pdf':
      return startsWith([0x25, 0x50, 0x44, 0x46]); // %PDF
    case 'image/jpeg':
      return startsWith([0xFF, 0xD8]);
    case 'image/png':
      return startsWith([0x89, 0x50, 0x4E, 0x47]);
    default:
      return false;
  }
}

// ---------------------------------------------------------------------------
// Extraction: RawExtraction (untrusted) vs ConfirmedField (verified)
// ---------------------------------------------------------------------------

/// One field read by the extractor. UNTRUSTED: machine output only, never
/// shown as fact until a human confirms it.
class RawField {
  const RawField({
    required this.name,
    required this.value,
    required this.confidence,
    required this.sourceDocId,
  });

  /// Machine field name, e.g. 'full_name', 'date_of_birth', 'id_number'.
  final String name;
  final String value;

  /// 0..1 — how sure the extractor claims to be. Still untrusted.
  final double confidence;
  final String sourceDocId;
}

/// The untrusted output of one extraction run. Kept strictly separate from
/// [ConfirmedField]: there is no conversion method on this class on purpose.
class RawExtraction {
  RawExtraction({
    required this.documentId,
    required this.fileName,
    required this.fields,
    this.provenance = 'mock-ocr-simulator',
    DateTime? extractedAt,
  }) : extractedAt = extractedAt ?? DateTime.now();

  final String documentId;
  final String fileName;
  final List<RawField> fields;

  /// Where this output came from. Always 'mock-ocr-simulator' until a real
  /// OCR provider is wired in (Stage 4 follow-up).
  final String provenance;
  final DateTime extractedAt;

  RawField? field(String name) {
    for (final f in fields) {
      if (f.name == name) return f;
    }
    return null;
  }
}

/// A field a HUMAN has explicitly verified. This is the only kind of field
/// the rest of the app may treat as fact.
///
/// There is deliberately NO implicit way to get here from [RawField]:
/// use [confirmField], which requires the verified value and who verified it.
class ConfirmedField {
  const ConfirmedField({
    required this.name,
    required this.value,
    required this.verifiedBy,
    required this.verifiedAt,
    this.sourceDocId,
  });

  final String name;
  final String value;

  /// Who verified it, e.g. 'user'.
  final String verifiedBy;
  final DateTime verifiedAt;
  final String? sourceDocId;
}

/// The ONLY bridge from untrusted to trusted: records an explicit human
/// decision. The caller supplies the final value (which may be a correction
/// of the raw value) and who verified it.
ConfirmedField confirmField(
  RawField raw, {
  required String confirmedValue,
  required String verifiedBy,
}) {
  return ConfirmedField(
    name: raw.name,
    value: confirmedValue,
    verifiedBy: verifiedBy,
    verifiedAt: DateTime.now(),
    sourceDocId: raw.sourceDocId,
  );
}

/// Extract structured fields from a validated document.
abstract class DocumentExtractor {
  Future<RawExtraction> extract(DocumentFile file);
}

/// Clearly-labeled OCR SIMULATOR. Deterministic (same file name -> same
/// output), makes no network calls, uses no API keys. Replace with a real
/// provider implementation of [DocumentExtractor] when one is chosen.
class MockOcrExtractor implements DocumentExtractor {
  @override
  Future<RawExtraction> extract(DocumentFile file) async {
    // Fail fast on bad files, exactly like a real provider client would.
    validateDocument(file);

    // Deterministic pseudo-data derived from the file name so repeated runs
    // agree with each other. These are obviously fake placeholder values.
    final h = file.fileName.hashCode.abs();
    const names = ['Abebe Tesfaye', 'Hanna Girma', 'Dawit Alemu'];
    const dobs = ['1998-04-12', '1990-11-03', '2001-07-25'];
    String pick(List<String> xs) => xs[h % xs.length];

    final docId = 'mockdoc_${h % 100000}';
    return RawExtraction(
      documentId: docId,
      fileName: file.fileName,
      fields: [
        RawField(
          name: 'full_name',
          value: pick(names),
          confidence: 0.80 + (h % 18) / 100,
          sourceDocId: docId,
        ),
        RawField(
          name: 'date_of_birth',
          value: pick(dobs),
          confidence: 0.75 + (h % 20) / 100,
          sourceDocId: docId,
        ),
        RawField(
          name: 'id_number',
          value: 'ET-${(h % 9000 + 1000)}-${(h % 900 + 100)}',
          confidence: 0.70 + (h % 25) / 100,
          sourceDocId: docId,
        ),
      ],
    );
  }
}

// ---------------------------------------------------------------------------
// Conflict detection: surface disagreements, never auto-resolve
// ---------------------------------------------------------------------------

/// Identity fields that must agree across sources. A disagreement on any of
/// these is a conflict the user must resolve — never the machine.
const List<String> identityFieldNames = [
  'full_name',
  'date_of_birth',
  'id_number',
];

String _normalize(String v) =>
    v.trim().toLowerCase().replaceAll(RegExp(r'\s+'), ' ');

/// Compare [identityFieldNames] across extraction sources. Every field with
/// two or more distinct values becomes an [IssueItem] of kind 'conflict'
/// whose [IssueItem.options] hold the candidate values.
///
/// This function only REPORTS: it never sets [IssueItem.resolution].
/// Resolution happens through [resolveIdentityConflict], which requires an
/// explicit user choice and records it as a [ConfirmedField].
List<IssueItem> detectIdentityConflicts(
  List<RawExtraction> sources, {
  List<String> identityFields = identityFieldNames,
}) {
  final issues = <IssueItem>[];
  for (final fieldName in identityFields) {
    // Collect one value per source (first occurrence wins per source).
    final bySource = <String, String>{}; // sourceDocId -> raw value
    for (final src in sources) {
      final f = src.field(fieldName);
      if (f != null && f.value.trim().isNotEmpty) {
        bySource.putIfAbsent(src.documentId, () => f.value);
      }
    }
    // Distinct values after normalization.
    final distinct = <String, String>{}; // normalized -> display value
    for (final v in bySource.values) {
      distinct.putIfAbsent(_normalize(v), () => v);
    }
    if (distinct.length > 1) {
      final label = fieldName.replaceAll('_', ' ');
      issues.add(IssueItem(
        id: 'conflict_${fieldName}_${DateTime.now().millisecondsSinceEpoch}',
        kind: 'conflict',
        title: 'Conflicting $label',
        detail:
            '${bySource.length} documents disagree on the $label: ${distinct.values.map((v) => '"$v"').join(' vs ')}. '
            'Please choose the correct value.',
        options: distinct.values.toList(),
      ));
    }
  }
  return issues;
}

/// Record the user's explicit choice for a conflict. Returns the confirmed
/// field; the caller is expected to mark the issue resolved in the store.
///
/// Throws [ArgumentError] if [chosenValue] is not one of the issue's options
/// — the user can only pick between surfaced candidates, nothing is invented.
ConfirmedField resolveIdentityConflict(
  IssueItem issue, {
  required String chosenValue,
  required String verifiedBy,
}) {
  if (issue.kind != 'conflict') {
    throw ArgumentError('Issue ${issue.id} is not a conflict.');
  }
  if (!issue.options.contains(chosenValue)) {
    throw ArgumentError(
        'Chosen value is not one of the conflicting options.');
  }
  return ConfirmedField(
    name: issue.id,
    value: chosenValue,
    verifiedBy: verifiedBy,
    verifiedAt: DateTime.now(),
  );
}
