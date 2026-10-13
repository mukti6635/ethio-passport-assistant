/// Supabase implementation of the ETHIO repository interfaces.
///
/// STATUS (Phase 7; compiled and tested since Phase 8):
/// AUTHENTICATION is implemented with supabase_flutter
/// (sign-in, sign-up, sign-out, session restoration, auth-state stream,
/// SDK-managed token refresh; session persisted in flutter_secure_storage
/// via a gotrue LocalStorage adapter). The task/document repositories
/// below remain documented skeletons: the app talks to the ETHIO gateway
/// for agent tasks and approvals (see backend/gateway_client.dart), and
/// these repositories are only for a future direct-to-Supabase mode.
///
/// Secrets: the anon key is safe to ship (RLS protects data), but the
/// SERVICE ROLE key must NEVER be in this file, in source control, or in
/// the app. It lives only on the backend server / Supabase dashboard.
library;

import 'dart:async';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:supabase_flutter/supabase_flutter.dart' as sb;

import '../models/task.dart';
import 'repository.dart';

/// Configuration for the Supabase project, from the dashboard
/// (Project Settings → API) via --dart-define values. Keep the
/// service-role key OUT of the app.
class SupabaseConfig {
  const SupabaseConfig({
    required this.projectUrl,
    required this.anonKey,
  });

  final String projectUrl; // e.g. https://xyzcompany.supabase.co
  final String anonKey; // anon/public key — safe to embed (RLS enforced)

  /// Validating constructor: returns null when either value is missing
  /// or blank, so callers can treat "not configured" as data, not an
  /// exception. Pure and unit-testable.
  static SupabaseConfig? tryCreate(String? projectUrl, String? anonKey) {
    final url = projectUrl?.trim() ?? '';
    final key = anonKey?.trim() ?? '';
    if (url.isEmpty || key.isEmpty) return null;
    return SupabaseConfig(projectUrl: url, anonKey: key);
  }

  /// Reads the compile-time defines ETHIO_SUPABASE_URL and
  /// ETHIO_SUPABASE_ANON_KEY. Returns null when unconfigured.
  static SupabaseConfig? fromDefines() => tryCreate(
        const String.fromEnvironment('ETHIO_SUPABASE_URL'),
        const String.fromEnvironment('ETHIO_SUPABASE_ANON_KEY'),
      );
}

/// Auth failure with a user-presentable message. Never carries tokens.
class EthioAuthException implements Exception {
  EthioAuthException(this.message);
  final String message;
  @override
  String toString() => message;
}

/// gotrue session persistence backed by flutter_secure_storage, so the
/// session (including the refresh token) lives in the platform keystore
/// rather than plain preferences.
class SecureSessionStorage extends sb.LocalStorage {
  SecureSessionStorage([FlutterSecureStorage? storage])
      : _storage = storage ?? const FlutterSecureStorage();

  final FlutterSecureStorage _storage;
  static const _key = 'ethio.supabase.session';

  @override
  Future<void> initialize() async {}

  @override
  Future<bool> hasAccessToken() async =>
      (await _storage.read(key: _key)) != null;

  @override
  Future<String?> accessToken() => _storage.read(key: _key);

  @override
  Future<void> persistSession(String persistSessionString) =>
      _storage.write(key: _key, value: persistSessionString);

  @override
  Future<void> removePersistedSession() => _storage.delete(key: _key);
}

/// Initializes the Supabase SDK once at app start. Token refresh and
/// session restoration are handled by the SDK (auto-refresh enabled by
/// default in supabase_flutter; the persisted session is restored from
/// [SecureSessionStorage] before the first frame needs it).
Future<void> initializeSupabase(SupabaseConfig config) async {
  await sb.Supabase.initialize(
    url: config.projectUrl,
    publishableKey: config.anonKey,
    authOptions: sb.FlutterAuthClientOptions(
      authFlowType: sb.AuthFlowType.pkce,
      localStorage: SecureSessionStorage(),
    ),
  );
}

class _SupabaseSession implements AuthSession {
  _SupabaseSession(this._session, this._signOut, {this.currentSession});

  final sb.Session _session;
  final Future<void> Function() _signOut;

  /// Reads the SDK's CURRENT session at access time. gotrue replaces
  /// the Session object on every token refresh, so a session captured
  /// at sign-in goes stale; [accessToken] must never serve the
  /// captured copy when a fresher one exists. Null in contexts that
  /// only have the captured session.
  final sb.Session? Function()? currentSession;

  @override
  String get userId => _session.user.id;

  @override
  String get email => _session.user.email ?? '';

  /// The user's current access token (JWT) for gateway calls. The SDK
  /// refreshes it automatically; always read it fresh, never cache it.
  String get accessToken =>
      currentSession?.call()?.accessToken ?? _session.accessToken;

  @override
  Future<void> signOut() => _signOut();
}

/// Supabase-backed authentication.
///
/// Requires [initializeSupabase] to have run first (AppServices does
/// this in main). All errors are surfaced as [EthioAuthException] with
/// presentable messages; no token is ever included in an error.
class SupabaseAuthRepository implements AuthRepository {
  SupabaseAuthRepository(this.config);

  final SupabaseConfig config;

  sb.GoTrueClient get _auth => sb.Supabase.instance.client.auth;

  AuthSession? _map(sb.Session? session) => session == null
      ? null
      : _SupabaseSession(session, signOut,
          currentSession: () => _auth.currentSession);

  @override
  AuthSession? get current => _map(_auth.currentSession);

  /// The current access token, or null when signed out. Read fresh on
  /// every gateway call so a refreshed token is picked up immediately.
  String? get currentAccessToken => _auth.currentSession?.accessToken;

  @override
  Stream<AuthSession?> get onAuthChanged =>
      _auth.onAuthStateChange.map((state) => _map(state.session));

  @override
  Future<AuthSession> signInWithEmail(String email, String password) async {
    try {
      final res = await _auth.signInWithPassword(
        email: email.trim(),
        password: password,
      );
      final session = res.session;
      if (session == null) {
        throw EthioAuthException('Sign-in did not return a session.');
      }
      return _SupabaseSession(session, signOut,
          currentSession: () => _auth.currentSession);
    } on sb.AuthException catch (e) {
      throw EthioAuthException('Sign-in failed: ${e.message}');
    }
  }

  @override
  Future<void> signUpWithEmail(String email, String password) async {
    try {
      await _auth.signUp(email: email.trim(), password: password);
    } on sb.AuthException catch (e) {
      throw EthioAuthException('Sign-up failed: ${e.message}');
    }
  }

  @override
  Future<void> signOut() async {
    try {
      await _auth.signOut();
    } on sb.AuthException catch (e) {
      throw EthioAuthException('Sign-out failed: ${e.message}');
    }
  }
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
  Future<void> resolveIssue(String taskId, String issueId, String resolution) =>
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
  Stream<ApprovalStatus> watchCheckpoint(String taskId, ApprovalKind kind) {
    throw UnimplementedError(
        'Use Supabase realtime on public.checkpoints filtered by task.');
  }

  @override
  Future<void> logEvent(
      String taskId, String event, Map<String, String> metadata) {
    const sensitive = {
      'otp',
      'code',
      'pin',
      'password',
      'secret',
      'token',
      'id_number',
      'document',
      'card'
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
