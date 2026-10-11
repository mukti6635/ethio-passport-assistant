import 'package:ethio/app.dart';
import 'package:ethio/models/task.dart';
import 'package:ethio/state/task_store.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// Scroll-into-view + tap + settle, for screens without looping timers.
Future<void> tapVisible(WidgetTester tester, Finder finder) async {
  await tester.ensureVisible(finder);
  await tester.pumpAndSettle();
  await tester.tap(finder);
  await tester.pumpAndSettle();
}

/// End-to-end smoke test: walks the full generic task pipeline with the
/// Passport service, proving every screen builds and the flow connects.
void main() {
  testWidgets('full passport task flow works end to end',
      (WidgetTester tester) async {
    await tester.pumpWidget(const EthioApp());
    await tester.pumpAndSettle();

    // --- Home ---
    expect(find.text('What do you need help with?'), findsOneWidget);
    expect(find.text('ETHIO'), findsOneWidget);
    for (final label in [
      'Passport',
      'Visa',
      "Driver's License",
      'Certificates',
      'Business Services',
      'Other Government Services',
    ]) {
      expect(find.text(label), findsOneWidget);
    }

    // --- Intake: pick Passport service ---
    await tapVisible(tester, find.text('Passport'));
    expect(find.text("Let's get started"), findsOneWidget);

    // Step 1: purpose = Renewal
    await tapVisible(tester, find.text('Renewal'));
    await tapVisible(tester, find.text('Continue'));

    // Step 2: full name
    await tester.enterText(find.byType(TextField), 'Abebe Tesfaye');
    await tester.pump();
    await tapVisible(tester, find.text('Continue'));

    // Step 3: date of birth via picker
    await tapVisible(tester, find.text('YYYY-MM-DD'));
    await tester.tap(find.text('OK'));
    await tester.pumpAndSettle();
    await tapVisible(tester, find.text('Continue'));

    // Step 4: phone, then finish
    await tester.enterText(find.byType(TextField), '+251911234567');
    await tester.pump();
    await tapVisible(tester, find.text('Create my task'));

    // --- Task overview ---
    expect(find.textContaining('Passport application'), findsOneWidget);
    expect(find.text('Next step'), findsOneWidget);

    // --- Requirements -> Upload ---
    await tapVisible(tester, find.text('Next step'));
    expect(find.text("What you'll need"), findsOneWidget);
    // Open the upload screen via the first requirement tile.
    await tapVisible(tester, find.text('National ID / Kebele ID'));

    // Add one sample document per requirement (4 for passport).
    final addButtons = find.text('Add document');
    expect(addButtons.evaluate().length, 4);
    for (var i = 0; i < 4; i++) {
      await tester.ensureVisible(addButtons.first);
      await tester.pumpAndSettle();
      await tester.tap(addButtons.first);
      await tester.pump();
    }
    await tester.pumpAndSettle();

    // Remove one document again to prove removal works.
    await tapVisible(tester, find.byIcon(Icons.delete_outline).first);
    await tester.tap(find.text('Remove'));
    await tester.pumpAndSettle();

    // --- Review extracted info ---
    await tapVisible(tester, find.text('Continue to review'));
    expect(find.text('Check your information'), findsOneWidget);
    expect(find.text('Abebe Tesfaye'), findsOneWidget);

    // Edit a field.
    await tapVisible(tester, find.text('Edit').first);
    await tester.enterText(find.byType(TextField).last, 'Abebe Tesfaye Jr');
    await tester.tap(find.text('Save'));
    await tester.pumpAndSettle();
    expect(find.text('Abebe Tesfaye Jr'), findsOneWidget);

    await tapVisible(tester, find.text('Confirm and continue'));

    // --- Missing info / conflicts ---
    expect(find.text('Needs your attention'), findsOneWidget);
    // Resolve the missing phone number.
    await tester.enterText(find.byType(TextField), '+251911234567');
    await tester.pump();
    await tapVisible(tester, find.text('Save answer').first);
    // Resolve the name conflict.
    await tapVisible(tester, find.text('Abebe Tesfaye').last);
    await tapVisible(tester, find.text('Save answer').last);

    // --- AI activity: fast-forward the simulated worker ---
    await tapVisible(tester, find.text('Continue'));
    expect(find.text('AI activity'), findsOneWidget);
    final task = TaskStore.instance.tasks.firstWhere(
        (t) => t.title.contains('Passport application'));
    while (TaskStore.instance.advanceAiStep(task)) {}
    await tester.pumpAndSettle();
    await tapVisible(tester, find.text('Continue'));

    // --- Approvals hub ---
    expect(find.text('Approvals needed'), findsOneWidget);

    // OTP approval (screen has a 1s resend timer: manual pumps only).
    await tester.tap(find.text('Verification code'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 200));
    await tester.pump(const Duration(milliseconds: 400));
    final boxes = find.byType(TextField);
    expect(boxes.evaluate().length, 6);
    for (var i = 0; i < 6; i++) {
      await tester.enterText(boxes.at(i), '${i + 1}');
      await tester.pump();
    }
    await tester.tap(find.text('Verify'));
    await tester.pump();
    await tester.pump(const Duration(seconds: 1));
    await tester.pumpAndSettle();
    expect(
        TaskStore.instance
            .taskById(task.id)!
            .approvals
            .firstWhere((a) => a.kind == ApprovalKind.otp)
            .approved,
        isTrue);

    // Payment approval.
    await tapVisible(tester, find.text('Payment'));
    await tapVisible(tester, find.text('Pay 600 ETB'));
    await tester.pump(const Duration(seconds: 3));
    await tester.pumpAndSettle();
    expect(find.text('Payment successful'), findsOneWidget);
    await tapVisible(tester, find.text('Done'));

    // Legal approval.
    await tapVisible(tester, find.text('Final legal review'));
    final checks = find.byType(Checkbox);
    expect(checks.evaluate().length, 3);
    for (var i = 0; i < 3; i++) {
      await tester.ensureVisible(checks.at(i));
      await tester.pumpAndSettle();
      await tester.tap(checks.at(i));
      await tester.pump();
    }
    await tapVisible(tester, find.text('Save review and finish'));

    // --- Appointments ---
    await tapVisible(tester, find.text('Continue'));
    expect(find.text('Book an appointment'), findsOneWidget);
    await tapVisible(tester, find.text('Confirm appointment'));
    expect(find.text('Appointment confirmed'), findsOneWidget);
    expect(find.textContaining('DEMO-'), findsOneWidget);

    await tapVisible(tester, find.text('Done'));
    expect(find.text('What do you need help with?'), findsOneWidget);
  });
}
