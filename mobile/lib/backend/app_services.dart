/// App-level service wiring (Phase 7).
///
/// Built once in main() before runApp:
/// - Reads Supabase config from --dart-define values; when present,
///   initializes the Supabase SDK (session restored from secure storage,
///   token refresh handled by the SDK) and creates the auth repository.
/// - Builds the [GatewaySessionConfig] the approval hub uses to resolve
///   a fresh gateway credential for every call: the signed-in user's
///   access token in jwt mode, the development key in devkey mode.
///
/// Missing configuration is data, not a crash: fields stay null and the
/// app runs its local flow exactly as before.
library;

import 'gateway_client.dart';
import 'supabase_adapter.dart';

class AppServices {
  AppServices._();

  static final AppServices instance = AppServices._();

  SupabaseConfig? supabaseConfig;
  SupabaseAuthRepository? auth;
  GatewaySessionConfig? gatewaySession;

  /// Non-fatal initialization problem (e.g. Supabase unreachable at
  /// startup). Shown in the approval hub; never contains secrets.
  String? initError;

  bool _initialized = false;

  Future<void> initialize() async {
    if (_initialized) return;
    _initialized = true;

    supabaseConfig = SupabaseConfig.fromDefines();
    final config = supabaseConfig;
    if (config != null) {
      try {
        await initializeSupabase(config);
        auth = SupabaseAuthRepository(config);
      } catch (e) {
        initError = 'Supabase initialization failed: $e';
        auth = null;
      }
    }

    final authRepo = auth;
    gatewaySession = GatewaySessionConfig.fromDefines(
      tokenProvider:
          authRepo == null ? null : () async => authRepo.currentAccessToken,
    );
  }
}
