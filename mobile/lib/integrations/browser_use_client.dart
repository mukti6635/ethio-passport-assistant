import 'dart:async';

/// Future integration point for the user's Browser Use WebUI backend.
///
/// This file is intentionally a stub: the prototype performs NO real browser
/// automation and makes NO network calls. When the backend is ready:
///
/// 1. Implement [BrowserUseClient] with HTTP calls to the WebUI backend
///    (see [HttpBrowserUseClient] below for the exact surface to fill in).
/// 2. Swap [BrowserUseClient.instance] to the real implementation.
/// 3. The AI activity screen will stream real [AutomationEvent]s instead of
///    the simulated timeline.
///
/// Nothing in the UI needs to change — it already consumes this interface.
abstract class BrowserUseClient {
  /// Shared instance. Defaults to the simulator; replace with the real
  /// client when the backend is connected.
  static BrowserUseClient instance = SimulatedBrowserUseClient();

  /// Check that the backend is reachable.
  Future<bool> ping();

  /// Ask the backend to start an automation job (e.g. "fill the passport
  /// application form with these values"). Returns a job id.
  Future<String> startJob({
    required String goal,
    required Map<String, String> inputs,
  });

  /// Stream of progress events for a job.
  Stream<AutomationEvent> watchJob(String jobId);

  /// Ask the backend to pause and wait for a human (OTP, CAPTCHA, payment).
  Future<void> requestHuman(String jobId, HumanCheckpoint checkpoint);
}

/// One progress event from an automation job.
class AutomationEvent {
  AutomationEvent({required this.label, required this.detail});

  final String label;
  final String detail;
  final DateTime at = DateTime.now();
}

/// A point where automation must stop and wait for the user.
enum HumanCheckpoint { otp, captcha, payment, legalSubmission }

/// Simulated backend used by the prototype. Emits a fixed, clearly-labeled
/// sequence of events with delays so the AI activity screen has something to
/// show. Replace with [HttpBrowserUseClient] for real automation.
class SimulatedBrowserUseClient implements BrowserUseClient {
  @override
  Future<bool> ping() async => false; // not connected in the prototype

  @override
  Future<String> startJob(
      {required String goal, required Map<String, String> inputs}) async {
    return 'sim_${DateTime.now().millisecondsSinceEpoch}';
  }

  @override
  Stream<AutomationEvent> watchJob(String jobId) async* {
    const script = [
      ('Opening the service portal', 'simulated'),
      ('Reading the form fields', 'simulated'),
      ('Filling known fields', 'simulated'),
      ('Waiting for human checkpoints', 'simulated'),
    ];
    for (final e in script) {
      await Future<void>.delayed(const Duration(seconds: 2));
      yield AutomationEvent(label: e.$1, detail: e.$2);
    }
  }

  @override
  Future<void> requestHuman(String jobId, HumanCheckpoint checkpoint) async {}
}

/// Outline of the real client. Fill in the HTTP calls to the Browser Use
/// WebUI backend when integrating.
///
/// ```dart
/// // Example shape (do not use as-is):
/// class HttpBrowserUseClient implements BrowserUseClient {
///   HttpBrowserUseClient({required this.baseUrl, this.apiKey});
///   final String baseUrl; // e.g. 'http://localhost:7788'
///   final String? apiKey;
///
///   @override
///   Future<bool> ping() async {
///     final res = await http.get(Uri.parse('$baseUrl/health'));
///     return res.statusCode == 200;
///   }
///   ... // startJob -> POST /jobs, watchJob -> SSE/websocket stream
/// }
/// ```
abstract class HttpBrowserUseClient implements BrowserUseClient {
  String get baseUrl;
}

// ---------------------------------------------------------------------------
// WebUiHttpAdapter — skeleton for the REAL Browser Use WebUI backend.
// ---------------------------------------------------------------------------
//
// STATUS: SKELETON. It compiles, and its auth/session/timeout/state-machine
// logic is real and unit-tested (see test/browser_adapter_test.dart), but
// every actual network call is a marked TODO: the official Gradio-only WebUI
// has no verified REST surface (see mock-portal/INTEGRATION_NOTES.md).
// Do NOT point this at a deployment until the endpoint paths, schemas, and
// auth scheme are filled in from that deployment's own documentation.
//
// REQUIRED CONFIG (supplied at wiring time, never hard-coded):
//   * baseUrl   — WebUI deployment base URL, e.g. 'http://127.0.0.1:7788'.
//   * apiKey    — bearer token, loaded from secure storage
//                 (flutter_secure_storage) at runtime. The official WebUI
//                 ships with NO api key; put it behind an auth gateway or
//                 use a wrapper build that issues one.
//   * sessionId — unique per user + task (e.g. 'user42/task-9f3a'). Sent on
//                 every request as X-Ethio-Session. NOTE: the official WebUI
//                 runs a single agent in one shared browser, so true
//                 isolation today means one WebUI instance per concurrent
//                 task; the session id lets a future multi-session backend
//                 route correctly.
//   * endpoint paths — real paths from YOUR deployment's API docs. The
//     defaults below are obvious '<SET-...-PATH>' placeholders and fail
//     loudly rather than silently hitting a wrong endpoint.
//
// This class is intentionally NOT wired as [BrowserUseClient.instance];
// the simulator remains the default until a real backend is configured.

/// Transport seam for the WebUI backend.
///
/// The adapter never performs raw HTTP itself: every request goes through a
/// [WebUiTransport]. In production this is a real HTTP implementation
/// (TODO — not yet written, see INTEGRATION_NOTES.md); in tests it is a
/// fake. This keeps the adapter's auth/session/timeout/state-machine logic
/// fully testable with zero network access.
abstract class WebUiTransport {
  Future<Map<String, dynamic>> get(String path,
      {Map<String, String>? headers});
  Future<Map<String, dynamic>> post(String path, Map<String, dynamic> body,
      {Map<String, String>? headers});
  void close();
}

/// Thrown when the adapter is used before a real [WebUiTransport] is wired.
class _MissingTransport implements WebUiTransport {
  Never _fail() {
    throw UnimplementedError(
        'WebUiHttpAdapter has no transport: wire a real WebUiTransport '
        'backed by HTTP (see mock-portal/INTEGRATION_NOTES.md) before '
        'pointing the adapter at a backend.');
  }

  @override
  Future<Map<String, dynamic>> get(String path,
          {Map<String, String>? headers}) =>
      _fail();

  @override
  Future<Map<String, dynamic>> post(String path, Map<String, dynamic> body,
          {Map<String, String>? headers}) =>
      _fail();

  @override
  void close() => _fail();
}

/// Base error for WebUI adapter failures.
class WebUiException implements Exception {
  WebUiException(this.message);
  final String message;
  @override
  String toString() => 'WebUiException: $message';
}

/// The backend rejected our credentials (or the deployment has no auth
/// configured and the gateway refused us).
class WebUiAuthException extends WebUiException {
  WebUiAuthException(super.message);
}

/// A request or a whole job exceeded its timeout.
class WebUiTimeoutException extends WebUiException {
  WebUiTimeoutException(super.message);
}

/// The remote job ended in a failed state.
class WebUiJobFailedException extends WebUiException {
  WebUiJobFailedException(super.message);
}

/// Lifecycle states a WebUI job can be in.
enum WebUiJobState {
  queued,
  running,
  paused,
  awaitingHuman,
  succeeded,
  failed,
  cancelled,
  timedOut,
  unknown,
}

WebUiJobState _parseJobState(String raw) {
  // TODO: align with the real deployment's status vocabulary.
  switch (raw.toLowerCase().replaceAll('_', '')) {
    case 'queued':
    case 'pending':
      return WebUiJobState.queued;
    case 'running':
    case 'inprogress':
      return WebUiJobState.running;
    case 'paused':
      return WebUiJobState.paused;
    case 'awaitinghuman':
      return WebUiJobState.awaitingHuman;
    case 'succeeded':
    case 'completed':
    case 'done':
    case 'finished':
      return WebUiJobState.succeeded;
    case 'failed':
    case 'error':
      return WebUiJobState.failed;
    case 'cancelled':
    case 'canceled':
      return WebUiJobState.cancelled;
    case 'timedout':
      return WebUiJobState.timedOut;
    default:
      return WebUiJobState.unknown;
  }
}

/// Point-in-time status of a WebUI job.
class WebUiJobStatus {
  WebUiJobStatus({required this.jobId, required this.state, this.log = const []});

  final String jobId;
  final WebUiJobState state;
  final List<String> log;

  bool get isTerminal => switch (state) {
        WebUiJobState.succeeded ||
        WebUiJobState.failed ||
        WebUiJobState.cancelled ||
        WebUiJobState.timedOut =>
          true,
        _ => false,
      };

  factory WebUiJobStatus.fromJson(String jobId, Map<String, dynamic> json) {
    // TODO: align keys with the real deployment's status schema.
    final raw = (json['state'] ?? json['status'] ?? 'unknown').toString();
    final log = switch (json['log']) {
      final List l => l.map((e) => e.toString()).toList(),
      _ => <String>[],
    };
    return WebUiJobStatus(jobId: jobId, state: _parseJobState(raw), log: log);
  }
}

/// Evidence returned by a finished job: the agent's reported outcome plus
/// any artifacts (screenshots, extracted fields) the backend exposes.
/// The adapter NEVER invents evidence; fields absent from the backend
/// response stay null/empty.
class WebUiEvidence {
  WebUiEvidence({
    required this.jobId,
    this.finalResult,
    this.artifacts = const [],
    this.extractedFields = const {},
  });

  final String jobId;
  final String? finalResult;
  final List<String> artifacts;
  final Map<String, String> extractedFields;

  factory WebUiEvidence.fromJson(String jobId, Map<String, dynamic> json) {
    // TODO: align keys with the real deployment's evidence schema.
    final result =
        (json['final_result'] ?? json['finalResult'] ?? json['result'])
            ?.toString();
    final artifacts = switch (json['artifacts']) {
      final List l => l.map((e) => e.toString()).toList(),
      _ => <String>[],
    };
    final extracted = switch (json['extracted'] ?? json['extracted_fields']) {
      final Map m => m.map((k, v) => MapEntry(k.toString(), v.toString())),
      _ => <String, String>{},
    };
    return WebUiEvidence(
      jobId: jobId,
      finalResult: result,
      artifacts: artifacts,
      extractedFields: extracted,
    );
  }
}

/// Skeleton HTTP adapter for a Browser Use WebUI backend.
///
/// Implements [BrowserUseClient] so the UI needs no changes when the backend
/// is connected: construct with real config + transport, then set
/// `BrowserUseClient.instance = adapter`.
class WebUiHttpAdapter implements HttpBrowserUseClient {
  WebUiHttpAdapter({
    required this.baseUrl,
    required this.apiKey,
    required this.sessionId,
    WebUiTransport? transport,
    this.requestTimeout = const Duration(seconds: 30),
    this.pollInterval = const Duration(seconds: 5),
    this.jobTimeout = const Duration(minutes: 30),
    // Defaults target the ETHIO gateway in /api (see api/README.md).
    // The adapter builds URLs as '<path>/<job_id>'.
    this.healthPath = '/health',
    this.runTaskPath = '/tasks',
    this.statusPath = '/tasks/status',
    this.pausePath = '/tasks/pause',
    this.resumePath = '/tasks/resume',
    this.cancelPath = '/tasks/cancel',
    this.evidencePath = '/tasks/evidence',
  }) : _transport = transport ?? _MissingTransport() {
    assert(baseUrl.isNotEmpty, 'baseUrl is required');
    assert(apiKey.isNotEmpty,
        'apiKey is required — load it from secure storage, never hard-code it');
    assert(sessionId.isNotEmpty, 'sessionId is required (per user + task)');
  }

  @override
  final String baseUrl;

  /// Bearer token. MUST come from secure storage at runtime; never a literal.
  final String apiKey;

  /// Unique per user + task. Sent as X-Ethio-Session on every request.
  final String sessionId;

  /// Per-request timeout (start/poll/pause/resume/cancel/evidence).
  final Duration requestTimeout;

  /// Delay between status polls in [watchJob].
  final Duration pollInterval;

  /// Overall deadline for [watchJob]; afterwards it throws
  /// [WebUiTimeoutException].
  final Duration jobTimeout;

  /// Endpoint paths. Defaults target the ETHIO gateway (`/api`); override
  /// only if your deployment uses different paths.
  final String healthPath;
  final String runTaskPath;
  final String statusPath;
  final String pausePath;
  final String resumePath;
  final String cancelPath;
  final String evidencePath;

  final WebUiTransport _transport;

  Map<String, String> get _headers => <String, String>{
        'Authorization': 'Bearer $apiKey',
        'X-Ethio-Session': sessionId,
        'Content-Type': 'application/json',
      };

  Future<Map<String, dynamic>> _get(String path) {
    // TODO: real network call plugs in here via WebUiTransport.
    return _transport.get(path, headers: _headers).timeout(
          requestTimeout,
          onTimeout: () => throw WebUiTimeoutException(
              'GET $path timed out after $requestTimeout'),
        );
  }

  Future<Map<String, dynamic>> _post(
      String path, Map<String, dynamic> body) {
    // TODO: real network call plugs in here via WebUiTransport.
    return _transport.post(path, body, headers: _headers).timeout(
          requestTimeout,
          onTimeout: () => throw WebUiTimeoutException(
              'POST $path timed out after $requestTimeout'),
        );
  }

  @override
  Future<bool> ping() async {
    try {
      // TODO: replace healthPath with the real health endpoint.
      final res = await _get(healthPath);
      return res['ok'] == true;
    } on WebUiException {
      return false; // backend unreachable/misbehaving — not a coding error.
    }
    // UnimplementedError (no transport wired) intentionally propagates.
  }

  @override
  Future<String> startJob({
    required String goal,
    required Map<String, String> inputs,
  }) async {
    // TODO: replace runTaskPath + payload/response schema with the real ones
    // from your WebUI deployment's API docs. Do NOT guess.
    final res = await _post(runTaskPath, <String, dynamic>{
      'goal': goal,
      'inputs': inputs,
      'session_id': sessionId,
    });
    final dynamic rawId = res['job_id'] ?? res['jobId'] ?? res['id'];
    if (rawId is! String || rawId.isEmpty) {
      throw WebUiException('WebUI did not return a job id (response: $res). '
          'Check the deployment\'s response schema and update startJob.');
    }
    return rawId;
  }

  /// Poll the job status once.
  Future<WebUiJobStatus> pollJob(String jobId) async {
    // TODO: replace statusPath + schema with the real ones.
    final res = await _get('$statusPath/$jobId');
    return WebUiJobStatus.fromJson(jobId, res);
  }

  @override
  Stream<AutomationEvent> watchJob(String jobId) async* {
    final deadline = DateTime.now().add(jobTimeout);
    var yielded = 0;
    while (true) {
      if (DateTime.now().isAfter(deadline)) {
        throw WebUiTimeoutException(
            'Timed out waiting for job $jobId after $jobTimeout');
      }
      final status = await pollJob(jobId);
      for (; yielded < status.log.length; yielded++) {
        yield AutomationEvent(label: status.log[yielded], detail: 'webui:$jobId');
      }
      if (status.isTerminal) {
        if (status.state == WebUiJobState.failed) {
          throw WebUiJobFailedException(
              'WebUI job $jobId ended in a failed state');
        }
        return;
      }
      await Future<void>.delayed(pollInterval);
    }
  }

  @override
  Future<void> requestHuman(String jobId, HumanCheckpoint checkpoint) async {
    // The agent must STOP and wait: OTP/CAPTCHA/payment/legal steps are
    // completed by the human in the ETHIO app (or via the WebUI VNC view),
    // never by the agent. The official WebUI exposes no checkpoint API, so
    // the skeleton pauses the job; [resumeJob] continues it afterwards.
    // (Server-side enforcement of checkpoints lands in Stage 7.)
    //
    // TODO: replace pausePath + payload with the deployment's equivalent.
    await _post('$pausePath/$jobId', <String, dynamic>{
      'checkpoint': checkpoint.name,
      'session_id': sessionId,
    });
  }

  /// Pause a running job (operator-initiated, no checkpoint attached).
  Future<void> pauseJob(String jobId) async {
    // TODO: replace pausePath with the real one.
    await _post('$pausePath/$jobId', <String, dynamic>{
      'session_id': sessionId,
    });
  }

  /// Resume a paused job.
  Future<void> resumeJob(String jobId) async {
    // TODO: replace resumePath with the real one.
    await _post('$resumePath/$jobId', <String, dynamic>{
      'session_id': sessionId,
    });
  }

  /// Cancel a job. Best-effort: the backend may already be in a terminal
  /// state, in which case the call should be a harmless no-op server-side.
  Future<void> cancelJob(String jobId) async {
    // TODO: replace cancelPath with the real one.
    await _post('$cancelPath/$jobId', <String, dynamic>{
      'session_id': sessionId,
    });
  }

  /// Fetch the evidence bundle for a finished job.
  Future<WebUiEvidence> fetchEvidence(String jobId) async {
    // TODO: replace evidencePath + schema with the real ones.
    final res = await _get('$evidencePath/$jobId');
    return WebUiEvidence.fromJson(jobId, res);
  }

  /// Release the underlying transport.
  void close() => _transport.close();
}
