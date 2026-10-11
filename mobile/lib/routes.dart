import 'package:flutter/material.dart';

import 'app.dart';
import 'screens/ai_activity_screen.dart';
import 'screens/approval_hub_screen.dart';
import 'screens/appointments_screen.dart';
import 'screens/captcha_screen.dart';
import 'screens/intake_screen.dart';
import 'screens/legal_screen.dart';
import 'screens/missing_info_screen.dart';
import 'screens/otp_screen.dart';
import 'screens/payment_screen.dart';
import 'screens/requirements_screen.dart';
import 'screens/review_screen.dart';
import 'screens/task_overview_screen.dart';
import 'screens/upload_screen.dart';

/// Central, named-route table. Every task-flow screen takes a task id
/// as [RouteSettings.arguments] so deep links stay simple.
class EthioRoutes {
  static Route<dynamic>? onGenerateRoute(RouteSettings settings) {
    final a = settings.arguments;
    switch (settings.name) {
      case '/':
        return _page(const MainTabs());
      case '/intake':
        return _page(IntakeScreen(serviceId: a as String));
      case '/task':
        return _page(TaskOverviewScreen(taskId: a as String));
      case '/requirements':
        return _page(RequirementsScreen(taskId: a as String));
      case '/upload':
        return _page(UploadScreen(taskId: a as String));
      case '/review':
        return _page(ReviewScreen(taskId: a as String));
      case '/issues':
        return _page(MissingInfoScreen(taskId: a as String));
      case '/ai':
        return _page(AiActivityScreen(taskId: a as String));
      case '/approvals':
        return _page(ApprovalHubScreen(taskId: a as String));
      case '/otp':
        return _page(OtpScreen(taskId: a as String));
      case '/captcha':
        return _page(CaptchaScreen(taskId: a as String));
      case '/payment':
        return _page(PaymentScreen(taskId: a as String));
      case '/legal':
        return _page(LegalScreen(taskId: a as String));
      case '/appointments':
        return _page(AppointmentsScreen(taskId: a as String));
      default:
        return _page(const MainTabs());
    }
  }

  static MaterialPageRoute<void> _page(Widget child) =>
      MaterialPageRoute<void>(builder: (_) => child);
}
