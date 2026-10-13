// Phase 7 tests: authentication configuration, gateway session
// resolution, authenticated request shape, and approval UI states.
//
// ALL TESTS IN THIS FILE ARE MOCKED / UNIT TESTS. They use fake token
// providers and package:http's MockClient — no network, no live
// Supabase project, no live gateway. They verify the client's side of
// the contract only; live authentication is verified manually with the
// smoke test in docs/DEVELOPMENT.md §6.
import 'dart:convert';

import 'package:ethio/backend/gateway_client.dart';
import 'package:ethio/backend/supabase_adapter.dart';
import 'package:ethio/widgets/backend_approval_card.dart';
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart' as http_testing;

void main() {
  group('SupabaseConfig.tryCreate (mocked)', () {
    test('missing or blank values mean "not configured"', () {
      expect(SupabaseConfig.tryCreate(null, null), isNull);
      expect(SupabaseConfig.tryCreate('', 'key'), isNull);
      expect(SupabaseConfig.tryCreate('https://x.supabase.co', '  '), isNull);
    });

    test('valid values are trimmed and kept', () {
      final c =
          SupabaseConfig.tryCreate(' https://x.supabase.co ', ' anon-key ');
      expect(c, isNotNull);
      expect(c!.projectUrl, 'https://x.supabase.co');
      expect(c.anonKey, 'anon-key');
    });
  });

  group('GatewaySessionConfig (mocked token provider)', () {
    test('jwt mode sends the current user token, resolved fresh', () async {
      var token = 'token-1';
      final cfg = GatewaySessionConfig(
        baseUrl: 'http://gw:8000',
        mode: GatewayAuthMode.jwt,
        sessionLabel: 'phone-a',
        tokenProvider: () async => token,
      );
      final first = await cfg.currentConfig();
      expect(first!.apiKey, 'token-1');
      expect(first.sessionId, 'phone-a');
      // Simulate an SDK token refresh: the NEXT call must carry the
      // new token, not a cached one.
      token = 'token-2';
      final second = await cfg.currentConfig();
      expect(second!.apiKey, 'token-2');
    });

    test(
        'jwt mode signed out resolves to no config (never a stale '
        'or empty credential)', () async {
      final cfg = GatewaySessionConfig(
        baseUrl: 'http://gw:8000',
        mode: GatewayAuthMode.jwt,
        tokenProvider: () async => null,
      );
      expect(await cfg.currentConfig(), isNull);
      expect(cfg.requiresSignIn, isTrue);
    });

    test('devkey mode uses the development credential only', () async {
      final cfg = GatewaySessionConfig(
        baseUrl: 'http://gw:8000',
        mode: GatewayAuthMode.devkey,
        devCredential: 'dev-key',
      );
      final resolved = await cfg.currentConfig();
      expect(resolved!.apiKey, 'dev-key');
      expect(cfg.requiresSignIn, isFalse);
    });

    test('fromDefines: no gateway URL means unconfigured', () {
      expect(
        GatewaySessionConfig.fromDefines(baseUrl: ''),
        isNull,
      );
    });

    test(
        'fromDefines: define-only dev setup still works (Phase 5 '
        'compatibility)', () {
      final cfg = GatewaySessionConfig.fromDefines(
        baseUrl: 'http://gw:8000',
        devCredential: 'dev-key',
        // no tokenProvider, no explicit mode
      );
      expect(cfg, isNotNull);
      expect(cfg!.mode, GatewayAuthMode.devkey);
    });
  });

  group('GatewayTaskClient (MockClient, no network)', () {
    const config = BackendApprovalConfig(
      baseUrl: 'http://gw:8000',
      apiKey: 'USER-TOKEN',
      sessionId: 'phone-a',
    );

    test('startTask sends the user token and never an owner id', () async {
      late http.Request seen;
      final client = GatewayTaskClient(
        config,
        client: http_testing.MockClient((req) async {
          seen = req;
          return http.Response(
              jsonEncode({'job_id': 'j1', 'state': 'queued'}), 201);
        }),
      );
      final job = await client.startTask(
          goal: 'Prepare my ID renewal', runner: 'worker');
      expect(job['job_id'], 'j1');
      expect(seen.headers['Authorization'], 'Bearer USER-TOKEN');
      expect(seen.headers['X-Ethio-Session'], 'phone-a');
      final body = jsonDecode(seen.body) as Map<String, dynamic>;
      expect(body['goal'], 'Prepare my ID renewal');
      expect(body['runner'], 'worker');
      // Ownership is the server's job: the client must not send any
      // owner/user field the gateway could be tricked into trusting.
      expect(body.containsKey('owner_id'), isFalse);
      expect(body.containsKey('user_id'), isFalse);
    });

    test(
        'getTask uses the gateway\'s real status route and maps a '
        '404 (another user\'s task) to GatewayException', () async {
      late http.Request seen;
      final client = GatewayTaskClient(
        config,
        client: http_testing.MockClient((req) async {
          seen = req;
          return http.Response(jsonEncode({'detail': 'job not found'}), 404);
        }),
      );
      await expectLater(
        client.getTask('someone-elses-job'),
        throwsA(isA<GatewayException>()
            .having((e) => e.statusCode, 'statusCode', 404)),
      );
      // Lock the route shape: the gateway serves /tasks/status/{id}
      // and /tasks/cancel/{id} (api/gateway.py), not /tasks/{id}.
      expect(seen.url.path, '/tasks/status/someone-elses-job');
    });

    test('cancelTask uses the gateway\'s real cancel route', () async {
      late http.Request seen;
      final client = GatewayTaskClient(
        config,
        client: http_testing.MockClient((req) async {
          seen = req;
          return http.Response(
              jsonEncode({'job_id': 'j1', 'state': 'cancelled'}), 200);
        }),
      );
      await client.cancelTask('j1');
      expect(seen.url.path, '/tasks/cancel/j1');
      expect(seen.method, 'POST');
    });

    test(
        'decideApproval posts the decision and returns the verified '
        'record', () async {
      late http.Request seen;
      final client = GatewayTaskClient(
        config,
        client: http_testing.MockClient((req) async {
          seen = req;
          return http.Response(
            jsonEncode({
              'approval_id': 'a1',
              'job_id': 'j1',
              'action_type': 'payment',
              'action_label': 'Pay',
              'consequence': 'Charges the fee (SIMULATED).',
              'params_summary': <String, String>{},
              'state': 'approved',
              'expires_at': 1893456000,
            }),
            200,
          );
        }),
      );
      final result = await client.decideApproval('a1', approve: true);
      expect(result!.state, 'approved');
      final body = jsonDecode(seen.body) as Map<String, dynamic>;
      expect(body['approve'], isTrue);
      expect(seen.headers['Authorization'], 'Bearer USER-TOKEN');
    });

    test('listPendingApprovals parses the pending list', () async {
      final client = GatewayTaskClient(
        config,
        client: http_testing.MockClient((req) async => http.Response(
              jsonEncode({
                'approvals': [
                  {
                    'approval_id': 'a1',
                    'job_id': 'j1',
                    'action_type': 'payment',
                    'action_label': 'Pay fee',
                    'consequence': 'c',
                    'params_summary': {'amount': 'ETB 200.00'},
                    'state': 'pending',
                    'expires_at': 1893456000,
                  }
                ]
              }),
              200,
            )),
      );
      final list = await client.listPendingApprovals();
      expect(list, hasLength(1));
      expect(list.single.isPending, isTrue);
      expect(list.single.paramsSummary['amount'], 'ETB 200.00');
    });
  });

  group('BackendApproval states (unit)', () {
    BackendApproval withState(String state) => BackendApproval.fromJson({
          'approval_id': 'a1',
          'job_id': 'j1',
          'action_type': 'payment',
          'action_label': 'Pay',
          'consequence': 'c',
          'params_summary': <String, String>{},
          'state': state,
          'expires_at': 1893456000,
        });

    test('only "pending" is actionable', () {
      expect(withState('pending').isPending, isTrue);
      for (final s in ['approved', 'rejected', 'expired', 'consumed']) {
        expect(withState(s).isPending, isFalse, reason: s);
      }
    });
  });

  group('BackendApprovalCard (widget, mocked)', () {
    BackendApproval approval(String state) => BackendApproval(
          approvalId: 'a1',
          jobId: 'j1',
          actionType: 'payment',
          actionLabel: 'Pay fee',
          consequence: 'Charges the fee (SIMULATED).',
          paramsSummary: const {},
          state: state,
          expiresAt: DateTime.now().add(const Duration(minutes: 5)),
        );

    Widget wrap(BackendApproval a) => MaterialApp(
          home: Scaffold(
            body: BackendApprovalCard(
              approval: a,
              baseUrl: 'http://gw:8000',
              apiKey: 'USER-TOKEN',
              sessionId: 'phone-a',
              // A client that fails loudly if the widget unexpectedly
              // tries the network in these render-only tests.
              httpClient: http_testing.MockClient(
                  (req) async => http.Response('{}', 500)),
            ),
          ),
        );

    testWidgets('pending approval shows Approve and Reject', (tester) async {
      await tester.pumpWidget(wrap(approval('pending')));
      expect(find.text('Approve'), findsOneWidget);
      expect(find.text('Reject'), findsOneWidget);
      expect(find.text('pending'), findsOneWidget);
    });

    testWidgets(
        'decided approvals show the outcome and NO action '
        'buttons (duplicate decisions impossible)', (tester) async {
      for (final state in ['approved', 'rejected', 'expired']) {
        await tester.pumpWidget(wrap(approval(state)));
        expect(find.text('Approve'), findsNothing, reason: state);
        expect(find.text('Reject'), findsNothing, reason: state);
        expect(find.text(state), findsWidgets, reason: state);
      }
    });

    // ---- Phase 13: the tap-to-decide path (previously render-only) ----

    Map<String, dynamic> decidedJson(String state) => {
          'approval_id': 'a1',
          'job_id': 'j1',
          'action_type': 'payment',
          'action_label': 'Pay fee',
          'consequence': 'Charges the fee (SIMULATED).',
          'params_summary': <String, String>{},
          'state': state,
          'expires_at': 1893456000,
        };

    Widget wrapDecide(
      http.Client client, {
      String apiKey = 'USER-TOKEN',
      Future<BackendApprovalConfig?> Function()? resolver,
    }) =>
        MaterialApp(
          home: Scaffold(
            body: BackendApprovalCard(
              approval: approval('pending'),
              baseUrl: 'http://gw:8000',
              apiKey: apiKey,
              sessionId: 'phone-a',
              httpClient: client,
              configResolver: resolver,
            ),
          ),
        );

    testWidgets('tapping Approve posts approve=true and shows the '
        'server-verified state', (tester) async {
      late http.Request seen;
      final client = http_testing.MockClient((req) async {
        seen = req;
        return http.Response(jsonEncode(decidedJson('approved')), 200);
      });
      await tester.pumpWidget(wrapDecide(client));
      await tester.tap(find.text('Approve'));
      await tester.pumpAndSettle();
      expect(seen.url.path, '/approvals/a1/decide');
      expect(jsonDecode(seen.body)['approve'], isTrue);
      expect(seen.headers['authorization'], 'Bearer USER-TOKEN');
      expect(find.textContaining('Decision recorded: approved'),
          findsOneWidget);
      expect(find.text('Approve'), findsNothing);
    });

    testWidgets('tapping Reject posts approve=false', (tester) async {
      late http.Request seen;
      final client = http_testing.MockClient((req) async {
        seen = req;
        return http.Response(jsonEncode(decidedJson('rejected')), 200);
      });
      await tester.pumpWidget(wrapDecide(client));
      await tester.tap(find.text('Reject'));
      await tester.pumpAndSettle();
      expect(jsonDecode(seen.body)['approve'], isFalse);
      expect(find.textContaining('Decision recorded: rejected'),
          findsOneWidget);
    });

    testWidgets('a failed decision shows the error, and Retry repeats '
        'the SAME direction (a rejection is never flipped)',
        (tester) async {
      final bodies = <Map<String, dynamic>>[];
      var calls = 0;
      final client = http_testing.MockClient((req) async {
        bodies.add(jsonDecode(req.body) as Map<String, dynamic>);
        calls++;
        if (calls == 1) {
          return http.Response(
              jsonEncode({'detail': 'gateway unavailable'}), 503);
        }
        return http.Response(jsonEncode(decidedJson('rejected')), 200);
      });
      await tester.pumpWidget(wrapDecide(client));
      await tester.tap(find.text('Reject'));
      await tester.pumpAndSettle();
      expect(find.text('Retry'), findsOneWidget);
      expect(find.textContaining('503'), findsOneWidget);
      await tester.tap(find.text('Retry'));
      await tester.pumpAndSettle();
      expect(calls, 2);
      expect(bodies[0]['approve'], isFalse);
      expect(bodies[1]['approve'], isFalse,
          reason: 'retry must repeat the rejection, not flip it');
      expect(find.textContaining('Decision recorded: rejected'),
          findsOneWidget);
    });

    testWidgets('fresh config resolver wins over the snapshot key at '
        'tap time (token rotation cannot fail the decision)',
        (tester) async {
      late http.Request seen;
      final client = http_testing.MockClient((req) async {
        seen = req;
        return http.Response(jsonEncode(decidedJson('approved')), 200);
      });
      await tester.pumpWidget(wrapDecide(
        client,
        apiKey: 'STALE-TOKEN',
        resolver: () async => const BackendApprovalConfig(
          baseUrl: 'http://gw:8000',
          apiKey: 'FRESH-TOKEN',
          sessionId: 'phone-a',
        ),
      ));
      await tester.tap(find.text('Approve'));
      await tester.pumpAndSettle();
      expect(seen.headers['authorization'], 'Bearer FRESH-TOKEN');
    });

    testWidgets('resolver reporting signed-out sends NOTHING and shows '
        'an honest error', (tester) async {
      var calls = 0;
      final client = http_testing.MockClient((req) async {
        calls++;
        return http.Response(jsonEncode(decidedJson('approved')), 200);
      });
      await tester.pumpWidget(wrapDecide(
        client,
        resolver: () async => null,
      ));
      await tester.tap(find.text('Approve'));
      await tester.pumpAndSettle();
      expect(calls, 0);
      expect(find.textContaining('Signed out'), findsOneWidget);
      // Still pending and actionable after signing back in.
      expect(find.text('Approve'), findsOneWidget);
    });
  });

  group('SecureSessionStorage (fake platform storage)', () {
    // In-memory stand-in for the platform keystore: same method
    // signatures as FlutterSecureStorage 9.x, no channel involved.
    test('persist → read-back → remove (the sign-out path)', () async {
      final fake = _FakeSecureStorage();
      final storage = SecureSessionStorage(fake);
      expect(await storage.hasAccessToken(), isFalse);
      expect(await storage.accessToken(), isNull);
      await storage.persistSession('{"refresh_token":"x"}');
      expect(await storage.hasAccessToken(), isTrue);
      expect(await storage.accessToken(), '{"refresh_token":"x"}');
      // gotrue calls removePersistedSession on sign-out: afterwards
      // nothing remains to restore a session from.
      await storage.removePersistedSession();
      expect(await storage.hasAccessToken(), isFalse);
      expect(await storage.accessToken(), isNull);
    });
  });
}

class _FakeSecureStorage extends FlutterSecureStorage {
  final Map<String, String> _map = {};

  @override
  Future<void> write({
    required String key,
    required String? value,
    IOSOptions? iOptions,
    AndroidOptions? aOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    MacOsOptions? mOptions,
    WindowsOptions? wOptions,
  }) async {
    if (value == null) {
      _map.remove(key);
    } else {
      _map[key] = value;
    }
  }

  @override
  Future<String?> read({
    required String key,
    IOSOptions? iOptions,
    AndroidOptions? aOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    MacOsOptions? mOptions,
    WindowsOptions? wOptions,
  }) async =>
      _map[key];

  @override
  Future<void> delete({
    required String key,
    IOSOptions? iOptions,
    AndroidOptions? aOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    MacOsOptions? mOptions,
    WindowsOptions? wOptions,
  }) async {
    _map.remove(key);
  }
}
