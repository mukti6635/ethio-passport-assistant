import 'package:ethio/app.dart';
import 'package:ethio/l10n/strings.dart';
import 'package:ethio/state/task_store.dart';
import 'package:ethio/widgets/privacy_notice.dart';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

/// Runs [body] with the view forced to [size] and returns the first line of
/// every RenderFlex overflow message reported while pumping. In widget tests
/// Flutter also surfaces overflow errors itself, so this is belt and braces.
Future<List<String>> captureOverflows(
    WidgetTester tester, Size size, Future<void> Function() body) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1.0;
  addTearDown(() {
    tester.view.resetPhysicalSize();
    tester.view.resetDevicePixelRatio();
  });
  final overflows = <String>[];
  final previous = FlutterError.onError;
  FlutterError.onError = (details) {
    if (details.toString().contains('overflowed')) {
      overflows.add(details.toString().split('\n').first.trim());
    }
    previous?.call(details);
  };
  try {
    await body();
  } finally {
    FlutterError.onError = previous;
  }
  return overflows;
}

void main() {
  group('narrow screens (360x640)', () {
    testWidgets('HomeScreen has no overflow', (WidgetTester tester) async {
      final overflows =
          await captureOverflows(tester, const Size(360, 640), () async {
        await tester.pumpWidget(const EthioApp());
        await tester.pumpAndSettle();
        // Scroll through the whole page so every section is laid out.
        await tester.drag(find.byType(SingleChildScrollView), const Offset(0, -1200));
        await tester.pumpAndSettle();
      });
      expect(overflows, isEmpty,
          reason: 'overflow at 360x640: ${overflows.join(' | ')}');
    });

    testWidgets('IntakeScreen has no overflow', (WidgetTester tester) async {
      final overflows =
          await captureOverflows(tester, const Size(360, 640), () async {
        await tester.pumpWidget(const EthioApp());
        await tester.pumpAndSettle();
        await tester.ensureVisible(find.text('Passport'));
        await tester.pumpAndSettle();
        await tester.tap(find.text('Passport'));
        await tester.pumpAndSettle();
        expect(find.text("Let's get started"), findsOneWidget);
      });
      expect(overflows, isEmpty,
          reason: 'overflow at 360x640: ${overflows.join(' | ')}');
    });
  });

  group('language row', () {
    testWidgets('Amharic switches language; Afaan Oromo honestly coming soon',
        (WidgetTester tester) async {
      await tester.pumpWidget(const EthioApp());
      await tester.pumpAndSettle();

      // English active; Amharic selectable; Afaan Oromo shows "coming soon".
      expect(find.text('English'), findsOneWidget);
      expect(find.text('አማርኛ'), findsOneWidget);
      expect(find.text('Afaan Oromoo · coming soon'), findsOneWidget);

      // Tapping Amharic switches the whole UI to Amharic.
      await tester.ensureVisible(find.text('አማርኛ'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('አማርኛ'));
      await tester.pumpAndSettle();
      expect(find.text('በምን ልረዳዎት?'), findsOneWidget);
      expect(find.text('What do you need help with?'), findsNothing);

      // Tapping Afaan Oromo explains it is not available yet.
      // (In Amharic mode the chip reads "Afaan Oromoo · በቅርቡ ይመጣል".)
      await tester.ensureVisible(find.text('Afaan Oromoo · በቅርቡ ይመጣል'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Afaan Oromoo · በቅርቡ ይመጣል'));
      await tester.pumpAndSettle();
      expect(
          find.text(
              'Afaan Oromoo በቅርቡ ይመጣል። መተግበሪያው ለዚህ ዝግጁ ሆኖ ተገንብቷል።'),
          findsOneWidget);

      // UI is still Amharic after dismissing the message.
      await tester.pump(const Duration(seconds: 4));
      await tester.pumpAndSettle();
      expect(find.text('በምን ልረዳዎት?'), findsOneWidget);
    });

    testWidgets('switching to English works', (WidgetTester tester) async {
      await tester.pumpWidget(const EthioApp());
      await tester.pumpAndSettle();
      // English chip is the selected, active language: tapping it keeps the
      // app in English.
      await tester.ensureVisible(find.text('English'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('English'));
      await tester.pumpAndSettle();
      expect(find.text('What do you need help with?'), findsOneWidget);
      expect(find.text('Services'), findsOneWidget);
    });
  });

  group('privacy notice', () {
    Widget harness(String bodyKey) => MaterialApp(
          locale: const Locale('en'),
          supportedLocales: const [Locale('en')],
          localizationsDelegates: const [
            EthioLocalizationsDelegate(),
            GlobalMaterialLocalizations.delegate,
            GlobalWidgetsLocalizations.delegate,
            GlobalCupertinoLocalizations.delegate,
          ],
          home: Scaffold(
            body: PrivacyNotice(
                titleKey: 'privacy_title', bodyKey: bodyKey),
          ),
        );

    testWidgets('explains data handling and acknowledges inline',
        (WidgetTester tester) async {
      await tester.pumpWidget(harness('privacy_upload'));
      await tester.pumpAndSettle();
      expect(find.text('Your information stays yours'), findsOneWidget);
      expect(find.textContaining('stays on this device'), findsOneWidget);
      // Acknowledgement is inline, not a dialog.
      expect(find.byType(AlertDialog), findsNothing);
      await tester.tap(find.text('I understand'));
      await tester.pumpAndSettle();
      expect(find.text('Understood'), findsOneWidget);
      expect(find.text('I understand'), findsNothing);
    });

    testWidgets('payment and legal variants explain their context',
        (WidgetTester tester) async {
      await tester.pumpWidget(harness('privacy_payment'));
      await tester.pumpAndSettle();
      expect(find.textContaining('no real money moves'), findsOneWidget);

      await tester.pumpWidget(harness('privacy_legal'));
      await tester.pumpAndSettle();
      expect(find.textContaining('Nothing you confirmed here is submitted'),
          findsOneWidget);
    });

    testWidgets('upload screen shows the notice before upload affordances',
        (WidgetTester tester) async {
      await tester.pumpWidget(const EthioApp());
      await tester.pumpAndSettle();
      final task = TaskStore.instance.createTask('passport', {});
      final context = tester.element(find.text('ETHIO'));
      Navigator.of(context).pushNamed('/upload', arguments: task.id);
      await tester.pumpAndSettle();

      expect(find.text('Your information stays yours'), findsOneWidget);
      // The notice comes before the "Add document" buttons in layout order.
      final noticeTop = tester.getTopLeft(find.byType(PrivacyNotice)).dy;
      final addTop =
          tester.getTopLeft(find.text('Add document').first).dy;
      expect(noticeTop, lessThan(addTop));
    });
  });
}
