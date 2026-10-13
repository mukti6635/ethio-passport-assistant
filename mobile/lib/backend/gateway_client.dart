/// Authenticated access to the ETHIO gateway (Phase 7).
///
/// Ownership rule: the gateway derives the task owner from the verified
/// bearer credential — NEVER from anything the client sends. This file
/// therefore sends only:
///   - `Authorization: Bearer <credential>` (the user's Supabase access
///     token in jwt mode; the development gateway key in devkey mode),
///   - `X-Ethio-Session: <label>` (a client label only; in jwt mode the
///     gateway ignores it for ownership),
///   - `session_id` in bodies (same label, kept for API compatibility).
///
/// Credentials are resolved FRESH for every call via
/// [GatewaySessionConfig.currentConfig], so a token refreshed by the
/// Supabase SDK is picked up automatically and a signed-out user simply
/// gets "no config" instead of a stale token.
library;

import 'dart:convert';

import 'package:http/http.dart' as http;

/// A backend approval request, as returned by GET /approvals/pending.
/// Never contains secrets, OTP values, or document contents.
class BackendApproval {
  BackendApproval({
    required this.approvalId,
    required this.jobId,
    required this.actionType,
    required this.actionLabel,
    required this.consequence,
    required this.paramsSummary,
    required this.state,
    required this.expiresAt,
  });

  final String approvalId;
  final String jobId;
  final String actionType;
  final String actionLabel;
  final String consequence;
  final Map<String, String> paramsSummary;
  final String state;
  final DateTime expiresAt;

  factory BackendApproval.fromJson(Map<String, dynamic> json) {
    final summary = <String, String>{};
    final raw = json['params_summary'];
    if (raw is Map) {
      for (final e in raw.entries) {
        summary[e.key.toString()] = e.value.toString();
      }
    }
    return BackendApproval(
      approvalId: json['approval_id'] as String,
      jobId: json['job_id'] as String,
      actionType: json['action_type'] as String,
      actionLabel: json['action_label'] as String? ?? '',
      consequence: json['consequence'] as String? ?? '',
      paramsSummary: summary,
      state: json['state'] as String? ?? 'pending',
      expiresAt: DateTime.fromMillisecondsSinceEpoch(
        ((json['expires_at'] as num? ?? 0) * 1000).toInt(),
        isUtc: true,
      ).toLocal(),
    );
  }

  bool get isPending => state == 'pending';
}

/// Connection details for one gateway call.
///
/// [apiKey] is the Bearer credential. In jwt mode it is the signed-in
/// user's short-lived Supabase access token; in devkey mode the
/// development gateway key. It must NEVER be a Supabase service-role key.
class BackendApprovalConfig {
  const BackendApprovalConfig({
    required this.baseUrl,
    required this.apiKey,
    required this.sessionId,
  });

  final String baseUrl;
  final String apiKey;

  /// Client-side session label only (see library doc). Not an owner id.
  final String sessionId;
}

/// How the app authenticates to the gateway.
enum GatewayAuthMode { jwt, devkey }

/// Resolves a fresh [BackendApprovalConfig] for each gateway call.
class GatewaySessionConfig {
  GatewaySessionConfig({
    required this.baseUrl,
    required this.mode,
    this.devCredential,
    this.sessionLabel = 'flutter-app',
    this.tokenProvider,
  });

  final String baseUrl;
  final GatewayAuthMode mode;

  /// Devkey mode only: the gateway's GATEWAY_API_KEY (development).
  final String? devCredential;

  /// Client label sent as X-Ethio-Session / body session_id.
  final String sessionLabel;

  /// Jwt mode: returns the current user's access token, or null when
  /// signed out. Called fresh for every gateway request.
  final Future<String?> Function()? tokenProvider;

  bool get requiresSignIn => mode == GatewayAuthMode.jwt;

  /// The config to use right now, or null when the gateway is not
  /// configured or (jwt mode) the user is signed out.
  Future<BackendApprovalConfig?> currentConfig() async {
    if (baseUrl.isEmpty) return null;
    switch (mode) {
      case GatewayAuthMode.devkey:
        final cred = devCredential ?? '';
        if (cred.isEmpty) return null;
        return BackendApprovalConfig(
          baseUrl: baseUrl,
          apiKey: cred,
          sessionId: sessionLabel,
        );
      case GatewayAuthMode.jwt:
        final token = await tokenProvider?.call();
        if (token == null || token.isEmpty) return null;
        return BackendApprovalConfig(
          baseUrl: baseUrl,
          apiKey: token,
          sessionId: sessionLabel,
        );
    }
  }

  /// Builds the session config from compile-time defines:
  ///   ETHIO_GATEWAY_URL            gateway base URL (required)
  ///   ETHIO_GATEWAY_AUTH_MODE      'jwt' (default when a token provider
  ///                                exists) or 'devkey'
  ///   ETHIO_GATEWAY_CREDENTIAL     devkey credential (devkey mode only)
  ///   ETHIO_SESSION_ID             client session label
  ///
  /// Returns null when ETHIO_GATEWAY_URL is unset (gateway section
  /// hidden, local flow only — the historical behavior).
  static GatewaySessionConfig? fromDefines({
    Future<String?> Function()? tokenProvider,
    String baseUrl = const String.fromEnvironment('ETHIO_GATEWAY_URL'),
    String modeName = const String.fromEnvironment('ETHIO_GATEWAY_AUTH_MODE'),
    String devCredential =
        const String.fromEnvironment('ETHIO_GATEWAY_CREDENTIAL'),
    String sessionLabel = const String.fromEnvironment('ETHIO_SESSION_ID'),
  }) {
    if (baseUrl.isEmpty) return null;
    final mode =
        modeName == 'devkey' ? GatewayAuthMode.devkey : GatewayAuthMode.jwt;
    // Without a token provider, jwt mode can never produce a config;
    // fall back to devkey only when a dev credential actually exists
    // (preserves the Phase 5 define-only development setup).
    final effectiveMode = (mode == GatewayAuthMode.jwt &&
            tokenProvider == null &&
            devCredential.isNotEmpty)
        ? GatewayAuthMode.devkey
        : mode;
    return GatewaySessionConfig(
      baseUrl: baseUrl,
      mode: effectiveMode,
      devCredential: devCredential.isEmpty ? null : devCredential,
      sessionLabel: sessionLabel.isEmpty ? 'flutter-app' : sessionLabel,
      tokenProvider: tokenProvider,
    );
  }
}

/// HTTP client for the gateway's task + approval endpoints.
///
/// Construct it from a freshly resolved [BackendApprovalConfig] (see
/// [GatewaySessionConfig.currentConfig]) so every call carries the
/// current credential. An [http.Client] can be injected for tests.
class GatewayTaskClient {
  GatewayTaskClient(this.config, {http.Client? client}) : _client = client;

  final BackendApprovalConfig config;
  final http.Client? _client;

  Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ${config.apiKey}',
        'X-Ethio-Session': config.sessionId,
      };

  Uri _uri(String path) => Uri.parse('${config.baseUrl}$path');

  Future<http.Response> _send(
      Future<http.Response> Function(http.Client c) fn) async {
    final own = _client == null;
    final c = _client ?? http.Client();
    try {
      return await fn(c).timeout(const Duration(seconds: 20));
    } finally {
      if (own) c.close();
    }
  }

  Future<Map<String, dynamic>> _json(Future<http.Response> pending) async {
    final res = await pending;
    if (res.statusCode < 200 || res.statusCode >= 300) {
      throw GatewayException(res.statusCode, _safeDetail(res.body));
    }
    if (res.body.isEmpty) return <String, dynamic>{};
    return jsonDecode(res.body) as Map<String, dynamic>;
  }

  static String _safeDetail(String body) {
    // Error bodies from the gateway contain a short `detail` string and
    // never credentials; still, cap the length echoed into the UI.
    try {
      final decoded = jsonDecode(body);
      if (decoded is Map && decoded['detail'] is String) {
        return decoded['detail'] as String;
      }
    } catch (_) {
      /* fall through to the raw body, truncated */
    }
    return body.length > 200 ? body.substring(0, 200) : body;
  }

  /// Starts an agent task. The owner is derived by the gateway from the
  /// bearer token; [BackendApprovalConfig.sessionId] is only a label.
  Future<Map<String, dynamic>> startTask({
    required String goal,
    Map<String, dynamic> inputs = const {},
    String runner = 'agent',
  }) =>
      _json(_send((c) => c.post(
            _uri('/tasks'),
            headers: _headers,
            body: jsonEncode({
              'goal': goal,
              'inputs': inputs,
              'runner': runner,
              'session_id': config.sessionId,
            }),
          )));

  /// Polls one task's status (404 when it belongs to another user).
  /// The gateway's route is /tasks/status/{id} (verified Phase 10
  /// against api/gateway.py — an earlier draft used /tasks/{id},
  /// which the gateway does not serve).
  Future<Map<String, dynamic>> getTask(String jobId) => _json(
      _send((c) => c.get(_uri('/tasks/status/$jobId'), headers: _headers)));

  /// Cancels one of the user's own tasks (/tasks/cancel/{id}).
  Future<Map<String, dynamic>> cancelTask(String jobId) => _json(
      _send((c) => c.post(_uri('/tasks/cancel/$jobId'), headers: _headers)));

  /// This user's pending approvals (server-filtered by owner).
  Future<List<BackendApproval>> listPendingApprovals() async {
    final body = await _json(
        _send((c) => c.get(_uri('/approvals/pending'), headers: _headers)));
    final list = body['approvals'] as List? ?? [];
    return list
        .map((e) => BackendApproval.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// Records an approve/reject decision. Returns the server's verified
  /// post-decision record — callers must display it, not assume success.
  Future<BackendApproval?> decideApproval(
    String approvalId, {
    required bool approve,
    String? reason,
  }) async {
    final body = await _json(_send((c) => c.post(
          _uri('/approvals/$approvalId/decide'),
          headers: _headers,
          body: jsonEncode({
            'approve': approve,
            if (reason != null) 'reason': reason,
            'session_id': config.sessionId,
          }),
        )));
    if (body.isEmpty) return null;
    return BackendApproval.fromJson(body);
  }
}

/// A gateway failure with an HTTP status and a presentable detail.
class GatewayException implements Exception {
  GatewayException(this.statusCode, this.detail);
  final int statusCode;
  final String detail;
  @override
  String toString() => 'Gateway error (HTTP $statusCode): $detail';
}
