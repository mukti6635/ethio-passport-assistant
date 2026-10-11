import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'l10n/strings.dart';
import 'routes.dart';
import 'screens/history_screen.dart';
import 'screens/home_screen.dart';
import 'screens/tasks_screen.dart';
import 'theme/ethio_theme.dart';

/// Root widget of the ETHIO prototype.
///
/// English is the default; Amharic ('am') is fully translated and
/// switchable from the home screen. Afaan Oromo ('om') is registered but
/// untranslated — every lookup falls back to English per key.
class EthioApp extends StatefulWidget {
  const EthioApp({super.key});

  /// Switch the app language. Ignored for untranslated locales.
  static void setLocale(BuildContext context, String code) {
    final state = context.findAncestorStateOfType<_EthioAppState>();
    state?._setLocale(code);
  }

  static Locale currentLocale(BuildContext context) {
    final state = context.findAncestorStateOfType<_EthioAppState>();
    return state?._locale ?? const Locale('en');
  }

  @override
  State<EthioApp> createState() => _EthioAppState();
}

class _EthioAppState extends State<EthioApp> {
  Locale _locale = const Locale('en');

  void _setLocale(String code) {
    // Only switch to locales with real translations; 'om' stays English
    // until its translations land (per-key fallback keeps it safe anyway).
    if (code != 'en' && code != 'am') return;
    if (_locale.languageCode == code) return;
    setState(() => _locale = Locale(code));
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'ETHIO',
      debugShowCheckedModeBanner: false,
      theme: EthioTheme.light(),
      locale: _locale,
      supportedLocales: const [Locale('en'), Locale('am'), Locale('om')],
      localizationsDelegates: const [
        EthioLocalizationsDelegate(),
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      localeResolutionCallback: (locale, supported) {
        if (locale == null) return const Locale('en');
        for (final s in supported) {
          if (s.languageCode == locale.languageCode) return s;
        }
        return const Locale('en');
      },
      initialRoute: '/',
      onGenerateRoute: EthioRoutes.onGenerateRoute,
    );
  }
}

/// Bottom-tab shell: Home / My Tasks / History.
class MainTabs extends StatefulWidget {
  const MainTabs({super.key});

  @override
  State<MainTabs> createState() => _MainTabsState();
}

class _MainTabsState extends State<MainTabs> {
  int _index = 0;

  static const _pages = <Widget>[
    HomeScreen(),
    TasksScreen(),
    HistoryScreen(),
  ];

  @override
  Widget build(BuildContext context) {
    final s = S.of(context);
    return Scaffold(
      body: IndexedStack(index: _index, children: _pages),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _index,
        onDestinationSelected: (i) => setState(() => _index = i),
        destinations: [
          NavigationDestination(
            icon: const Icon(Icons.home_outlined),
            selectedIcon: const Icon(Icons.home),
            label: s.t('tab_home'),
          ),
          NavigationDestination(
            icon: const Icon(Icons.assignment_outlined),
            selectedIcon: const Icon(Icons.assignment),
            label: s.t('tab_tasks'),
          ),
          NavigationDestination(
            icon: const Icon(Icons.history_outlined),
            selectedIcon: const Icon(Icons.history),
            label: s.t('tab_history'),
          ),
        ],
      ),
    );
  }
}
