// Document pipeline tests: file validation, mock extraction, conflict
// detection (never auto-resolved), and the type-level separation between
// untrusted [RawExtraction] output and user-verified [ConfirmedField] data.
import 'package:ethio/pipeline/document_pipeline.dart';
import 'package:flutter_test/flutter_test.dart';

const _okPng = DocumentFile(
  fileName: 'id_front.png',
  mimeType: 'image/png',
  sizeBytes: 500 * 1024,
  bytes: [0x89, 0x50, 0x4E, 0x47, 0x00],
);

RawExtraction _extraction(String docId, Map<String, String> values) {
  return RawExtraction(
    documentId: docId,
    fileName: '$docId.pdf',
    fields: values.entries
        .map((e) => RawField(
              name: e.key,
              value: e.value,
              confidence: 0.9,
              sourceDocId: docId,
            ))
        .toList(),
  );
}

void main() {
  group('file validation', () {
    test('accepts a valid PNG under the size limit', () {
      expect(tryValidate(_okPng), isEmpty);
    });

    test('accepts PDF and JPG too', () {
      expect(
        tryValidate(const DocumentFile(
          fileName: 'doc.pdf',
          mimeType: 'application/pdf',
          sizeBytes: 1000,
          bytes: [0x25, 0x50, 0x44, 0x46],
        )),
        isEmpty,
      );
      expect(
        tryValidate(const DocumentFile(
          fileName: 'photo.jpg',
          mimeType: '',
          sizeBytes: 1000, // MIME inferred from extension
          bytes: [0xFF, 0xD8, 0xFF],
        )),
        isEmpty,
      );
    });

    test('rejects oversized files with a typed error', () {
      const big = DocumentFile(
        fileName: 'huge.pdf',
        mimeType: 'application/pdf',
        sizeBytes: maxDocumentBytes + 1,
      );
      expect(
        () => validateDocument(big),
        throwsA(isA<DocumentValidationError>().having(
          (e) => e.kind,
          'kind',
          DocumentErrorKind.tooLarge,
        )),
      );
    });

    test('rejects unsupported types with a typed error', () {
      const txt = DocumentFile(
        fileName: 'notes.txt',
        mimeType: 'text/plain',
        sizeBytes: 100,
      );
      expect(
        () => validateDocument(txt),
        throwsA(isA<DocumentValidationError>().having(
          (e) => e.kind,
          'kind',
          DocumentErrorKind.unsupportedType,
        )),
      );
    });

    test('rejects empty files with a typed error', () {
      const empty = DocumentFile(
        fileName: 'empty.png',
        mimeType: 'image/png',
        sizeBytes: 0,
      );
      expect(
        () => validateDocument(empty),
        throwsA(isA<DocumentValidationError>().having(
          (e) => e.kind,
          'kind',
          DocumentErrorKind.emptyFile,
        )),
      );
    });

    test('rejects content that does not match the claimed type', () {
      const fake = DocumentFile(
        fileName: 'fake.png',
        mimeType: 'image/png',
        sizeBytes: 64,
        bytes: [0x25, 0x50, 0x44, 0x46], // actually a PDF header
      );
      expect(
        () => validateDocument(fake),
        throwsA(isA<DocumentValidationError>().having(
          (e) => e.kind,
          'kind',
          DocumentErrorKind.malformed,
        )),
      );
    });
  });

  group('mock extraction', () {
    test('returns structured fields with confidence, labeled as mock', () async {
      final out = await MockOcrExtractor().extract(_okPng);
      expect(out.provenance, 'mock-ocr-simulator');
      expect(out.fields, isNotEmpty);
      for (final f in out.fields) {
        expect(f.name, isNotEmpty);
        expect(f.value, isNotEmpty);
        expect(f.confidence, inInclusiveRange(0.0, 1.0));
      }
      expect(out.field('full_name'), isNotNull);
    });

    test('is deterministic for the same file', () async {
      final a = await MockOcrExtractor().extract(_okPng);
      final b = await MockOcrExtractor().extract(_okPng);
      expect(a.field('full_name')!.value, b.field('full_name')!.value);
    });

    test('refuses to extract an invalid file', () async {
      const big = DocumentFile(
        fileName: 'huge.pdf',
        mimeType: 'application/pdf',
        sizeBytes: maxDocumentBytes + 1,
      );
      expect(
        () => MockOcrExtractor().extract(big),
        throwsA(isA<DocumentValidationError>()),
      );
    });
  });

  group('conflict detection', () {
    test('conflicting identity fields produce conflicts, never resolution',
        () {
      final issues = detectIdentityConflicts([
        _extraction('doc_a', {'full_name': 'Abebe Tesfaye'}),
        _extraction('doc_b', {'full_name': 'Abebe Tesfay'}),
      ]);
      expect(issues, hasLength(1));
      final issue = issues.first;
      expect(issue.kind, 'conflict');
      expect(issue.options,
          containsAll(['Abebe Tesfaye', 'Abebe Tesfay']));
      // Never auto-resolved: resolution stays empty until the user chooses.
      expect(issue.resolution, isNull);
      expect(issue.resolved, isFalse);
    });

    test('agreeing sources produce no conflicts', () {
      final issues = detectIdentityConflicts([
        _extraction('doc_a', {'full_name': 'Abebe Tesfaye'}),
        _extraction('doc_b', {'full_name': '  abebe  tesfaye '}),
      ]);
      expect(issues, isEmpty);
    });

    test('each disagreeing identity field gets its own conflict', () {
      final issues = detectIdentityConflicts([
        _extraction('doc_a',
            {'full_name': 'Abebe Tesfaye', 'date_of_birth': '1998-04-12'}),
        _extraction('doc_b',
            {'full_name': 'Hanna Girma', 'date_of_birth': '1990-11-03'}),
      ]);
      expect(issues, hasLength(2));
      expect(issues.every((i) => i.resolved == false), isTrue);
    });

    test('resolving a conflict requires an explicit user choice', () {
      final issues = detectIdentityConflicts([
        _extraction('doc_a', {'full_name': 'Abebe Tesfaye'}),
        _extraction('doc_b', {'full_name': 'Abebe Tesfay'}),
      ]);
      final confirmed = resolveIdentityConflict(
        issues.first,
        chosenValue: 'Abebe Tesfaye',
        verifiedBy: 'user',
      );
      expect(confirmed, isA<ConfirmedField>());
      expect(confirmed.value, 'Abebe Tesfaye');
      expect(confirmed.verifiedBy, 'user');
    });

    test('cannot resolve with a value that was never surfaced', () {
      final issues = detectIdentityConflicts([
        _extraction('doc_a', {'full_name': 'Abebe Tesfaye'}),
        _extraction('doc_b', {'full_name': 'Abebe Tesfay'}),
      ]);
      expect(
        () => resolveIdentityConflict(
          issues.first,
          chosenValue: 'Invented Name',
          verifiedBy: 'user',
        ),
        throwsArgumentError,
      );
    });
  });

  group('raw vs confirmed separation (type level)', () {
    test('a RawField is not a ConfirmedField and has no path to become one',
        () {
      const raw = RawField(
        name: 'full_name',
        value: 'Abebe Tesfaye',
        confidence: 0.99,
        sourceDocId: 'd1',
      );
      expect(raw, isNot(isA<ConfirmedField>()));
      // No method on RawField/RawExtraction returns a ConfirmedField:
      // the only bridge is the explicit confirmField() call below.
    });

    test('raw output cannot be passed where confirmed data is required', () {
      void needsConfirmed(ConfirmedField f) => f.value;
      const raw = RawField(
        name: 'full_name',
        value: 'Abebe Tesfaye',
        confidence: 0.99,
        sourceDocId: 'd1',
      );
      expect(
        () => needsConfirmed(raw as dynamic),
        throwsA(isA<TypeError>()),
      );
    });

    test('confirmField requires an explicit value and verifier', () {
      const raw = RawField(
        name: 'full_name',
        value: 'Abebe Tesfaye',
        confidence: 0.9,
        sourceDocId: 'd1',
      );
      final confirmed = confirmField(
        raw,
        confirmedValue: 'Abebe Tesfay', // user corrected the OCR
        verifiedBy: 'user',
      );
      expect(confirmed.value, 'Abebe Tesfay');
      expect(confirmed.verifiedBy, 'user');
      expect(confirmed.verifiedAt, isA<DateTime>());
    });
  });
}
