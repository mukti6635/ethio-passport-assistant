/// ETHIO backend repository interfaces.
///
/// The Flutter app codes against these abstractions, never against a concrete
/// backend. Today the app uses the in-memory [TaskStore]; when the Supabase
/// project exists, `SupabaseTaskRepository` (see supabase_adapter.dart)
/// implements the same interface and the app switches with one line.
///
/// Security rules encoded here:
///  * Every method is scoped to the signed-in user; there is no "get any
///    user's task" method by design.
///  * Checkpoint authorization has no client-side path: the interface only
///    exposes `requestCheckpoint` (creates a *pending* row). The backend
///    service flips it to *authorized* after verifying the user's action.
///  * No method accepts or returns secrets, OTP codes, or document bytes.
library;

import '../models/task.dart';

/// Signed-in user session.
abstract class AuthSession {
  String get userId;
  String get email;
  Future<void> signOut();
}

/// Authentication. Implementations must keep tokens in secure storage.
abstract class AuthRepository {
  /// Current session, or null when signed out.
  AuthSession? get current;

  /// Stream of auth state changes.
  Stream<AuthSession?> get onAuthChanged;

  Future<AuthSession> signInWithEmail(String email, String password);
  Future<void> signUpWithEmail(String email, String password);
  Future<void> signOut();
}

/// Persistence for tasks and everything under them.
///
/// All methods operate on the current user's data only. Implementations MUST
/// enforce this server-side (RLS); the interface existing is not the control.
abstract class TaskRepository {
  // -- tasks -------------------------------------------------------------
  Future<List<ServiceTask>> listTasks({bool done = false});
  Future<ServiceTask?> getTask(String taskId);
  Future<ServiceTask> createTask(ServiceTask task);
  Future<void> updateTaskStage(String taskId, TaskStage stage);

  // -- requirements -------------------------------------------------------
  Future<void> setRequirementStatus(
      String taskId, String requirementId, String status);

  // -- documents (metadata only; bytes go to private storage) ------------
  Future<DocItem> registerDocument({
    required String taskId,
    required String requirementId,
    required String fileName,
    required String mimeType,
    required int sizeBytes,
    required String storagePath,
  });
  Future<void> deleteDocument(String taskId, String docId);

  /// Returns a short-lived signed URL for the user's own document.
  Future<Uri> signDocumentUrl(String storagePath);

  // -- extraction vs confirmed data (separate on purpose) ----------------
  Future<void> saveRawExtraction({
    required String taskId,
    required String documentId,
    required String fieldName,
    required String fieldValue,
    required double confidence,
  });
  Future<void> confirmField({
    required String taskId,
    required String fieldName,
    required String fieldValue,
  });

  // -- issues --------------------------------------------------------------
  Future<void> saveIssue(IssueItem issue, String taskId);
  Future<void> resolveIssue(
      String taskId, String issueId, String resolution);

  // -- checkpoints ----------------------------------------------------------
  /// Creates a *pending* checkpoint. There is deliberately no
  /// `authorizeCheckpoint` here: only the backend service may authorize,
  /// after verifying the user's explicit action.
  Future<void> requestCheckpoint({
    required String taskId,
    required ApprovalKind kind,
    Map<String, String> detail = const {},
  });
  Future<void> cancelCheckpoint({
    required String taskId,
    required ApprovalKind kind,
  });
  Stream<ApprovalStatus> watchCheckpoint(
      String taskId, ApprovalKind kind);

  // -- audit ----------------------------------------------------------------
  /// Non-sensitive events only. Implementations must reject sensitive keys.
  Future<void> logEvent(
      String taskId, String event, Map<String, String> metadata);
}

/// Private file storage (Supabase Storage `documents` bucket).
abstract class DocumentStorage {
  /// Upload bytes the user chose. The implementation validates size and
  /// MIME type before upload and stores under `<userId>/<taskId>/...`.
  Future<String> upload({
    required String taskId,
    required String fileName,
    required String mimeType,
    required List<int> bytes,
  });

  Future<void> delete(String storagePath);
}
