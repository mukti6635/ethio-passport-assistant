import 'dart:async';

import 'package:ethio/integrations/browser_use_client.dart';
import 'package:flutter_test/flutter_test.dart';

// ---------------------------------------------------------------------------
// Tests for the WebUiHttpAdapter skeleton and the simulator's honesty.
// No real network calls: every test runs against FakeWebUiTransport.
// ---------------------------------------------------------------------------

class RecordedCall {
  RecordedCall(this.method, this.path, this.body, this.headers);
  final String method;
  final String path;
  final Map<String, dynamic>? body;
  final Map<String, String> headers;
}

/// In-memory stand-in for a real HTTP transport. Records every request and
/// answers via a per-test handler.
class FakeWebUiTransport implements WebUiTransport {
  Future<Map<String, dynamic>> Function(RecordedCall call)? handler;
  final List<RecordedCall> calls = [];
  bool closed = false;

  Future<Map<String, dynamic>> _run(
    String method,
    String path,
    Map<String, dynamic>? body,
    Map<String, String>? headers,
  ) async {
    final call = RecordedCall(method, path, body, headers ?? const {});
    calls.add(call);
    final h = handler;
    if (h == null) return <String, dynamic>{};
    return h(call);
  }

  @override
  Future<Map<String, dynamic>> get(String path,
          {Map<String, String>? headers}) =>
      _run('GET', path, null, headers);

  @override
  Future<Map<String, dynamic>> post(String path, Map<String, dynamic> body,
          {Map<String, String>? headers}) =>
      _run('POST', path, body, headers);

  @override
  void close() {
    closed = true;
  }
}

WebUiHttpAdapter _adapter(
  FakeWebUiTransport transport, {
  String sessionId = 'user1/task1',
  Duration jobTimeout = const Duration(seconds: 2),
}) {
  return WebUiHttpAdapter(
    baseUrl: 'http://webui.test',
    apiKey: 'test-key',
    sessionId: sessionId,
    transport: transport,
    requestTimeout: const Duration(milliseconds: 200),
    pollInterval: const Duration(milliseconds: 10),
    jobTimeout: jobTimeout,
    healthPath: '/health',
    runTaskPath: '/run',
    statusPath: '/status',
    pausePath: '/pause',
    resumePath: '/resume',
    cancelPath: '/cancel',
    evidencePath: '/evidence',
  );
}

void main() {
  group('WebUiHttpAdapter state machine', () {
    test('start -> poll -> pause -> resume -> cancel', () async {
      final states = <String, String>{};
      final transport = FakeWebUiTransport();
      transport.handler = (call) async {
        if (call.path == '/run') {
          states['job-1'] = 'running';
          return {'job_id': 'job-1'};
        }
        if (call.path == '/status/job-1') {
          return {'state': states['job-1'], 'log': ['opened portal']};
        }
        if (call.path == '/pause/job-1') {
          states['job-1'] = 'paused';
          return {'ok': true};
        }
        if (call.path == '/resume/job-1') {
          states['job-1'] = 'running';
          return {'ok': true};
        }
        if (call.path == '/cancel/job-1') {
          states['job-1'] = 'cancelled';
          return {'ok': true};
        }
        return <String, dynamic>{};
      };
      final adapter = _adapter(transport);

      final jobId = await adapter.startJob(
          goal: 'fill the form', inputs: {'name': 'Abebe'});
      expect(jobId, 'job-1');

      var status = await adapter.pollJob(jobId);
      expect(status.state, WebUiJobState.running);
      expect(status.isTerminal, isFalse);

      await adapter.pauseJob(jobId);
      status = await adapter.pollJob(jobId);
      expect(status.state, WebUiJobState.paused);
      expect(status.isTerminal, isFalse);

      // requestHuman pauses with the checkpoint attached.
      await adapter.requestHuman(jobId, HumanCheckpoint.otp);
      final humanCall = transport.calls.lastWhere(
          (c) => c.path == '/pause/job-1' && c.body?['checkpoint'] == 'otp');
      expect(humanCall.body?['checkpoint'], 'otp');

      await adapter.resumeJob(jobId);
      status = await adapter.pollJob(jobId);
      expect(status.state, WebUiJobState.running);

      await adapter.cancelJob(jobId);
      status = await adapter.pollJob(jobId);
      expect(status.state, WebUiJobState.cancelled);
      expect(status.isTerminal, isTrue);
    });

    test('watchJob streams log events and completes on success', () async {
      var polls = 0;
      final transport = FakeWebUiTransport();
      transport.handler = (call) async {
        polls++;
        if (polls < 3) {
          return {
            'state': 'running',
            'log': ['step 1']
          };
        }
        return {
          'state': 'succeeded',
          'log': ['step 1', 'step 2', 'done']
        };
      };
      final adapter = _adapter(transport);

      final events = await adapter.watchJob('job-9').toList();
      expect(events.map((e) => e.label), ['step 1', 'step 2', 'done']);
      // Events are namespaced to the job; nothing is invented.
      expect(events.every((e) => e.detail == 'webui:job-9'), isTrue);
    });

    test('watchJob raises when the job fails', () async {
      final transport = FakeWebUiTransport();
      transport.handler = (call) async => {'state': 'failed', 'log': ['boom']};
      final adapter = _adapter(transport);

      await expectLater(
        adapter.watchJob('job-x').toList(),
        throwsA(isA<WebUiJobFailedException>()),
      );
    });
  });

  group('timeouts', () {
    test('startJob times out when the backend hangs', () async {
      final transport = FakeWebUiTransport();
      transport.handler =
          (call) => Completer<Map<String, dynamic>>().future; // never resolves
      final adapter = _adapter(transport);

      expect(
        () => adapter.startJob(goal: 'x', inputs: {}),
        throwsA(isA<WebUiTimeoutException>()),
      );
    });

    test('ping returns false (not throw) on timeout', () async {
      final transport = FakeWebUiTransport();
      transport.handler =
          (call) => Completer<Map<String, dynamic>>().future;
      final adapter = _adapter(transport);

      expect(await adapter.ping(), isFalse);
    });

    test('watchJob gives up after jobTimeout', () async {
      final transport = FakeWebUiTransport();
      transport.handler = (call) async => {'state': 'running', 'log': []};
      final adapter =
          _adapter(transport, jobTimeout: const Duration(milliseconds: 300));

      await expectLater(
        adapter.watchJob('job-z').toList(),
        throwsA(isA<WebUiTimeoutException>()),
      );
    });
  });

  group('session isolation', () {
    test('two sessions never see each other\'s jobs', () async {
      final jobsBySession = <String>{};
      final transport = FakeWebUiTransport();
      transport.handler = (call) async {
        final session = call.headers['X-Ethio-Session']!;
        if (call.path == '/run') {
          jobsBySession.add(session);
          return {'job_id': 'job-shared'};
        }
        if (call.path == '/status/job-shared') {
          // A session only sees jobs it started itself.
          if (!jobsBySession.contains(session)) {
            return {'state': 'unknown', 'log': []};
          }
          return {
            'state': 'running',
            'log': ['working for $session']
          };
        }
        return <String, dynamic>{};
      };

      final alice = _adapter(transport, sessionId: 'alice/task1');
      final bob = _adapter(transport, sessionId: 'bob/task2');

      final jobId = await alice.startJob(goal: 'g', inputs: {});

      // Bob never started a job: the same id is invisible to him.
      final bobStatus = await bob.pollJob(jobId);
      expect(bobStatus.state, WebUiJobState.unknown);

      // Alice sees her own job.
      final aliceStatus = await alice.pollJob(jobId);
      expect(aliceStatus.state, WebUiJobState.running);
      expect(aliceStatus.log, ['working for alice/task1']);

      // Every request carried auth + the correct session header.
      expect(transport.calls, isNotEmpty);
      for (final call in transport.calls) {
        expect(call.headers['Authorization'], 'Bearer test-key');
        expect(call.headers['X-Ethio-Session'], isNotNull);
      }
      final runCalls =
          transport.calls.where((c) => c.path == '/run').toList();
      expect(runCalls, hasLength(1));
      expect(runCalls.single.headers['X-Ethio-Session'], 'alice/task1');
    });
  });

  group('auth + evidence', () {
    test('startJob throws when the backend returns no job id', () async {
      final transport = FakeWebUiTransport();
      transport.handler = (call) async => {'unexpected': 'shape'};
      final adapter = _adapter(transport);

      expect(
        () => adapter.startJob(goal: 'g', inputs: {}),
        throwsA(isA<WebUiException>()),
      );
    });

    test('fetchEvidence parses the deployment payload, invents nothing',
        () async {
      final transport = FakeWebUiTransport();
      transport.handler = (call) async => {
            'final_result': 'form filled',
            'artifacts': ['shot1.png'],
            'extracted': {'name': 'Abebe'},
          };
      final adapter = _adapter(transport);

      final evidence = await adapter.fetchEvidence('job-1');
      expect(evidence.jobId, 'job-1');
      expect(evidence.finalResult, 'form filled');
      expect(evidence.artifacts, ['shot1.png']);
      expect(evidence.extractedFields['name'], 'Abebe');

      // Absent fields stay empty, never invented.
      final sparseTransport = FakeWebUiTransport();
      sparseTransport.handler = (call) async => <String, dynamic>{};
      final sparse = await _adapter(sparseTransport).fetchEvidence('job-2');
      expect(sparse.finalResult, isNull);
      expect(sparse.artifacts, isEmpty);
      expect(sparse.extractedFields, isEmpty);
    });

    test('close releases the transport', () {
      final transport = FakeWebUiTransport();
      final adapter = _adapter(transport);
      adapter.close();
      expect(transport.closed, isTrue);
    });
  });

  group('skeleton safety', () {
    test('adapter without a transport fails loudly, not silently', () {
      final adapter = WebUiHttpAdapter(
        baseUrl: 'http://webui.test',
        apiKey: 'k',
        sessionId: 's',
      );
      expect(() => adapter.ping(), throwsA(isA<UnimplementedError>()));
    });

    test('default instance is still the simulator', () {
      expect(BrowserUseClient.instance, isA<SimulatedBrowserUseClient>());
    });
  });

  group('simulator honesty', () {
    test('simulator never claims a real submission', () async {
      final sim = SimulatedBrowserUseClient();

      expect(await sim.ping(), isFalse); // not connected in the prototype

      final id = await sim.startJob(goal: 'submit passport', inputs: {});
      expect(id.startsWith('sim_'), isTrue);

      final events = await sim.watchJob(id).toList();
      expect(events, isNotEmpty);
      const banned = ['submitt', 'approv', 'confirm', 'success', 'complete'];
      for (final event in events) {
        expect(event.detail, 'simulated');
        for (final word in banned) {
          expect(
            event.label.toLowerCase().contains(word),
            isFalse,
            reason:
                'simulator must never claim "$word" (saw: "${event.label}")',
          );
        }
      }

      // requestHuman is a harmless no-op in the simulator.
      await sim.requestHuman(id, HumanCheckpoint.payment);
    });
  });
}
