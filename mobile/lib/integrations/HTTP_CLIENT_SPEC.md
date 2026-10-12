# HttpBrowserUseClient — Implementation Specification

**Status:** NOT IMPLEMENTED. Requires Flutter SDK to write and verify.
**Reason:** No Dart/Flutter toolchain in this environment; shipping uncompiled
Dart risks syntax errors.

## What to build

Replace `SimulatedBrowserUseClient` with a real HTTP client in
`lib/integrations/browser_use_client.dart`.

### Dependencies

Add to `pubspec.yaml`:
```yaml
dependencies:
  http: ^1.2.0
  flutter_secure_storage: ^9.0.0
```

### Interface changes needed

The current `BrowserUseClient` interface is missing operations the gateway
supports. Extend it:

```dart
abstract class BrowserUseClient {
  static BrowserUseClient instance = SimulatedBrowserUseClient();

  Future<bool> ping();
  Future<String> startJob({required String goal, required Map<String, String> inputs});
  Stream<AutomationEvent> watchJob(String jobId);

  // ADD:
  Future<void> pauseJob(String jobId);
  Future<void> resumeJob(String jobId);
  Future<void> cancelJob(String jobId);
  Future<String?> getEvidence(String jobId);
  Future<void> requestHuman(String jobId, HumanCheckpoint checkpoint);
}
```

### HttpBrowserUseClient implementation sketch

```dart
import 'dart:async';
import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class HttpBrowserUseClient implements BrowserUseClient {
  HttpBrowserUseClient({required this.baseUrl});

  final String baseUrl;
  final _storage = const FlutterSecureStorage();
  static const _apiKeyKey = 'ethio_gateway_api_key';
  static const _sessionKey = 'ethio_session_id';

  Future<Map<String, String>> _headers() async {
    final apiKey = await _storage.read(key: _apiKeyKey);
    final sessionId = await _storage.read(key: _sessionKey);
    if (apiKey == null || apiKey.isEmpty) {
      throw StateError('Gateway API key not configured');
    }
    return {
      'Authorization': 'Bearer $apiKey',
      'X-Ethio-Session': sessionId ?? '',
      'Content-Type': 'application/json',
    };
  }

  @override
  Future<bool> ping() async {
    try {
      final res = await http.get(Uri.parse('$baseUrl/health'))
          .timeout(const Duration(seconds: 5));
      return res.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  @override
  Future<String> startJob({required String goal, required Map<String, String> inputs}) async {
    final headers = await _headers();
    final sessionId = headers['X-Ethio-Session']!;
    final res = await http.post(
      Uri.parse('$baseUrl/tasks'),
      headers: headers,
      body: jsonEncode({'goal': goal, 'inputs': inputs, 'session_id': sessionId}),
    ).timeout(const Duration(seconds: 30));
    if (res.statusCode == 202) {
      return jsonDecode(res.body)['job_id'] as String;
    } else if (res.statusCode == 409) {
      // Session already has an active job; extract its ID from the error.
      final detail = jsonDecode(res.body)['detail'] as String;
      final match = RegExp(r'[0-9a-f]{32}').firstMatch(detail);
      if (match != null) return match.group(0)!;
      throw StateError('Job conflict: $detail');
    } else if (res.status_code == 429) {
      throw StateError('Server busy, try again later');
    }
    throw StateError('Failed to start job: ${res.statusCode}');
  }

  @override
  Stream<AutomationEvent> watchJob(String jobId) async* {
    // Poll /tasks/status/{jobId} every 3s, yield AutomationEvent per log line.
    final seen = <String>{};
    while (true) {
      final headers = await _headers();
      final res = await http.get(
        Uri.parse('$baseUrl/tasks/status/$jobId'),
        headers: headers,
      ).timeout(const Duration(seconds: 10));
      if (res.statusCode != 200) throw StateError('Job not found');
      final data = jsonDecode(res.body);
      final state = data['state'] as String;
      for (final line in (data['log'] as List)) {
        final s = line as String;
        if (seen.add(s)) {
          yield AutomationEvent(label: state, detail: s);
        }
      }
      if (_isTerminal(state)) break;
      await Future.delayed(const Duration(seconds: 3));
    }
  }

  bool _isTerminal(String state) =>
      const {'succeeded', 'failed', 'cancelled', 'timed_out'}.contains(state);

  @override
  Future<void> pauseJob(String jobId) => _post('/tasks/pause/$jobId', {});
  @override
  Future<void> resumeJob(String jobId) => _post('/tasks/resume/$jobId', {});
  @override
  Future<void> cancelJob(String jobId) => _post('/tasks/cancel/$jobId', {});

  @override
  Future<String?> getEvidence(String jobId) async {
    final headers = await _headers();
    final res = await http.get(
      Uri.parse('$baseUrl/tasks/evidence/$jobId'),
      headers: headers,
    ).timeout(const Duration(seconds: 10));
    if (res.statusCode != 200) return null;
    return jsonDecode(res.body)['final_result'] as String?;
  }

  @override
  Future<void> requestHuman(String jobId, HumanCheckpoint checkpoint) =>
      _post('/tasks/pause/$jobId', {'checkpoint': checkpoint.name});

  Future<void> _post(String path, Map<String, dynamic> body) async {
    final headers = await _headers();
    final res = await http.post(
      Uri.parse('$baseUrl$path'),
      headers: headers,
      body: jsonEncode(body),
    ).timeout(const Duration(seconds: 10));
    if (res.statusCode != 200) {
      throw StateError('Request failed: ${res.statusCode}');
    }
  }
}
```

### Verification steps (requires Flutter SDK)

1. `flutter pub get`
2. `flutter analyze` — must be clean
3. `flutter test` — existing 57 tests must pass
4. Manual: point `baseUrl` at a running gateway, verify `ping()` returns true

### Security notes

- API key lives ONLY in `flutter_secure_storage`, never in code or prefs.
- Session ID generated per install, stored securely.
- Never log the API key or session ID.
