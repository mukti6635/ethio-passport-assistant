/// Supabase implementation of the ETHIO repository interfaces.
///
/// STATUS: skeleton. It compiles and documents the exact mapping, but every
/// method that needs a live project throws [UnimplementedError] until the
/// Supabase project is configured (see backend/README.md).
///
/// Secrets: the anon key is safe to ship (RLS protects data), but the
/// SERVICE ROLE key must NEVER be in this file, in source control, or in
/// the app. It lives only on the backend server / Supabase dashboard.
library;

import 'dart:async';

import '../models/task.dart';
import 'repository.dart';

/// Configuration for the Supabase project. Fill from the Supabase dashboard
/// (Project Settings → API). Keep the service-role key OUT of the app.
class SupabaseConfig {
  const SupabaseConfig({
    required this.projectUrl,
    required this.anonKey,
  });

  final String projectUrl; // e.g. https://xyzcompany.supabase.co
  final String anonKey; // anon/public key — safe to embed (RLS enforced)
}

/// Supabase-backed auth. Tokens go to flutter_secure_storage in the real
/// implementation (add the dependency when wiring this up).
class SupabaseAuthRepository implements AuthRepository {
  SupabaseAuthRepository(this.config);

  final SupabaseConfig config;

  @override
  AuthSession? get current => null;

  @override
  Stream<AuthSession?> get onAuthChanged =>
      const Stream<AuthSession?>.empty();

  @override
  Future<AuthSession> signInWithEmail(String email, String password) {
    throw UnimplementedError(
        'Configure SupabaseConfig and add the supabase_flutter dependency.');
  }

  @override
  Future<void> signUpWithEmail(String email, String password) {
    throw UnimplementedError(
        'Configure SupabaseConfig and add the supabase_flutter dependency.');
  }

  @override
  Future<void> signOut() async {}
}

/// Supabase-backed task repository.
///
/// Table mapping (see backend/migrations/):
///   ServiceTask        → public.tasks
///   RequirementStatus  → public.requirements
///   DocItem            → public.documents (+ storage.objects)
///   RawExtraction      → public.extractions
///   ConfirmedField     → public.confirmed_fields
///   IssueItem          → public.issues
///   ApprovalItem       → public.checkpoints
///
/// RLS guarantees users only ever see their own rows; this class additionally
/// never issues cross-user queries.
class SupabaseTaskRepository implements TaskRepository {
  SupabaseTaskRepository(this.config);

  final SupabaseConfig config;

  Never _todo([String what = '']) =>
      throw UnimplementedError('Supabase not configured yet. $what');

  @override
  Future<List<ServiceTask>> listTasks({bool done = false}) => _todo();

  @override
  Future<ServiceTask?> getTask(String taskId) => _todo();

  @override
  Future<ServiceTask> createTask(ServiceTask task) => _todo();

  @override
  Future<void> updateTaskStage(String taskId, TaskStage stage) => _todo();

  @override
  Future<void> setRequirementStatus(
          String taskId, String requirementId, String status) =>
      _todo();

  @override
  Future<DocItem> registerDocument({
    required String taskId,
    required String requirementId,
    required String fileName,
    required String mimeType,
    required int sizeBytes,
    required String storagePath,
  }) =>
      _todo();

  @override
  Future<void> deleteDocument(String taskId, String docId) => _todo();

  @override
  Future<Uri> signDocumentUrl(String storagePath) => _todo();

  @override
  Future<void> saveRawExtraction({
    required String taskId,
    required String documentId,
    required String fieldName,
    required String fieldValue,
    required double confidence,
  }) =>
      _todo();

  @override
  Future<void> confirmField({
    required String taskId,
    required String fieldName,
    required String fieldValue,
  }) =>
      _todo();

  @override
  Future<void> saveIssue(IssueItem issue, String taskId) => _todo();

  @override
  Future<void> resolveIssue(
          String taskId, String issueId, String resolution) =>
      _todo();

  @override
  Future<void> requestCheckpoint({
    required String taskId,
    required ApprovalKind kind,
    Map<String, String> detail = const {},
  }) =>
      _todo('Creates a pending checkpoint row; authorization is server-side.');

  @override
  Future<void> cancelCheckpoint({
    required String taskId,
    required ApprovalKind kind,
  }) =>
      _todo();

  @override
  Stream<ApprovalStatus> watchCheckpoint(
      String taskId, ApprovalKind kind) {
    throw UnimplementedError(
        'Use Supabase realtime on public.checkpoints filtered by task.');
  }

  @override
  Future<void> logEvent(
      String taskId, String event, Map<String, String> metadata) {
    const sensitive = {
      'otp', 'code', 'pin', 'password', 'secret', 'token',
      'id_number', 'document', 'card'
    };
    for (final key in metadata.keys) {
      if (sensitive.any((s) => key.toLowerCase().contains(s))) {
        throw ArgumentError(
            'Refusing to log sensitive key "$key". Audit events must never '
            'contain secrets, codes, or identity data.');
      }
    }
    return _todo();
  }
}

/// Supabase Storage adapter for the private `documents` bucket.
class SupabaseDocumentStorage implements DocumentStorage {
  SupabaseDocumentStorage(this.config);

  final SupabaseConfig config;

  static const maxBytes = 10 * 1024 * 1024;
  static const allowedMime = {
    'application/pdf',
    'image/jpeg',
    'image/png',
  };

  @override
  Future<String> upload({
    required String taskId,
    required String fileName,
    required String mimeType,
    required List<int> bytes,
  }) {
    if (!allowedMime.contains(mimeType)) {
      throw ArgumentError('Unsupported file type: $mimeType');
    }
    if (bytes.length > maxBytes) {
      throw ArgumentError('File too large (max 10 MB).');
    }
    throw UnimplementedError('Supabase not configured yet.');
  }

  @override
  Future<void> delete(String storagePath) {
    throw UnimplementedError('Supabase not configured yet.');
  }
}
