import 'package:flutter/material.dart';

import 'app.dart';
import 'backend/app_services.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  // Initializes Supabase (when configured via --dart-define) and the
  // gateway session config before the first frame. Failures are
  // recorded on AppServices.initError and never block the local flow.
  await AppServices.instance.initialize();
  runApp(const EthioApp());
}
