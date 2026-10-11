import 'package:flutter/material.dart';

import '../data/service_catalog.dart';
import '../app.dart';
import '../l10n/strings.dart';
import '../state/task_store.dart';
import '../theme/ethio_theme.dart';
import '../widgets/cards.dart';
import '../widgets/core.dart';

/// ETHIO home: logo, tagline, "What do you need help with?", service cards,
/// free-text box + Start button, language row.
class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  final _textController = TextEditingController();

  @override
  void dispose() {
    _textController.dispose();
    super.dispose();
  }

  /// Route free text to the best-matching service (generic, keyword based).
  String _detectService(String text) {
    final t = text.toLowerCase();
    if (t.contains('passport')) {
      return 'passport';
    }
    if (t.contains('visa')) {
      return 'visa';
    }
    if (t.contains('driv') || t.contains('license')) {
      return 'license';
    }
    if (t.contains('certificate') ||
        t.contains('birth') ||
        t.contains('marriage')) {
      return 'certificates';
    }
    if (t.contains('business') || t.contains('company')) {
      return 'business';
    }
    return 'other';
  }

  void _startFromText() {
    final text = _textController.text.trim();
    final serviceId = text.isEmpty ? 'other' : _detectService(text);
    final store = TaskStore.instance;
    final task = store.createTask(
      serviceId,
      text.isEmpty ? {} : {'describe': text},
      titleOverride: text.isEmpty
          ? null
          : 'Request: ${text.length > 42 ? '${text.substring(0, 42)}…' : text}',
    );
    _textController.clear();
    if (!mounted) return;
    Navigator.of(context).pushNamed('/task', arguments: task.id);
  }

  void _openService(String serviceId) {
    Navigator.of(context).pushNamed('/intake', arguments: serviceId);
  }

  @override
  Widget build(BuildContext context) {
    final s = S.of(context);
    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            const PrototypeBanner(),
            Expanded(
              child: SingleChildScrollView(
                padding: const EdgeInsets.fromLTRB(20, 20, 20, 32),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    _LogoHeader(),
                    const SizedBox(height: 28),
                    Text(s.t('home_heading'), style: EthioText.h1),
                    const SizedBox(height: 8),
                    Text(s.t('home_sub'), style: EthioText.bodyMuted),
                    const SizedBox(height: 20),
                    SectionTitle(title: s.t('services_title')),
                    GridView.builder(
                      shrinkWrap: true,
                      physics: const NeverScrollableScrollPhysics(),
                      gridDelegate:
                          const SliverGridDelegateWithFixedCrossAxisCount(
                        crossAxisCount: 2,
                        mainAxisSpacing: 12,
                        crossAxisSpacing: 12,
                        // Taller than square so longer service titles and
                        // subtitles fit on narrow phones without overflowing.
                        childAspectRatio: 0.85,
                      ),
                      itemCount: serviceCatalog.length,
                      itemBuilder: (context, i) {
                        final def = serviceCatalog[i];
                        return ServiceCard(
                          icon: def.icon,
                          accent: def.accent,
                          title: s.t(def.titleKey),
                          subtitle: s.t(def.descKey),
                          onTap: () => _openService(def.id),
                        );
                      },
                    ),
                    const SizedBox(height: 24),
                    TextField(
                      controller: _textController,
                      minLines: 2,
                      maxLines: 4,
                      textInputAction: TextInputAction.done,
                      decoration: InputDecoration(
                        hintText: s.t('describe_hint'),
                        prefixIcon: const Icon(Icons.chat_bubble_outline,
                            color: EthioColors.primary),
                      ),
                      onSubmitted: (_) => _startFromText(),
                    ),
                    const SizedBox(height: 12),
                    EthioButton(
                      label: s.t('start_button'),
                      icon: Icons.arrow_forward,
                      onPressed: _startFromText,
                    ),
                    const SizedBox(height: 28),
                    _LanguageRow(),
                    const SizedBox(height: 20),
                    Text(
                      s.t('not_affiliated'),
                      textAlign: TextAlign.center,
                      style: EthioText.caption,
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// ETHIO brand mark: drawn entirely in code, no image downloads.
class _LogoHeader extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    final s = S.of(context);
    return Row(
      children: [
        Container(
          width: 62,
          height: 62,
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(18),
            gradient: const LinearGradient(
              begin: Alignment.topLeft,
              end: Alignment.bottomRight,
              colors: [Color(0xFF12A37C), EthioColors.primaryDark],
            ),
            boxShadow: const [
              BoxShadow(
                color: Color(0x3312A37C),
                blurRadius: 16,
                offset: Offset(0, 6),
              ),
            ],
          ),
          child: const Icon(Icons.auto_awesome,
              color: Colors.white, size: 32),
        ),
        const SizedBox(width: 14),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('ETHIO',
                  style: TextStyle(
                      fontSize: 26,
                      fontWeight: FontWeight.w900,
                      letterSpacing: 2,
                      color: EthioColors.ink)),
              Text(s.t('app_tagline'),
                  style: const TextStyle(
                      fontSize: 14,
                      fontWeight: FontWeight.w600,
                      color: EthioColors.primary)),
            ],
          ),
        ),
      ],
    );
  }
}

/// Language row: English + Amharic switchable, Afaan Oromo honestly
/// marked as coming soon.
class _LanguageRow extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    final s = S.of(context);
    final current = EthioApp.currentLocale(context).languageCode;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(s.t('language'), style: EthioText.smallBold),
        const SizedBox(height: 10),
        Wrap(
          spacing: 10,
          runSpacing: 10,
          children: [
            _LangChip(
              label: s.t('lang_en'),
              selected: current == 'en',
              onTap: () => EthioApp.setLocale(context, 'en'),
            ),
            _LangChip(
              label: s.t('lang_am'),
              selected: current == 'am',
              onTap: () => EthioApp.setLocale(context, 'am'),
            ),
            _LangChip(
              label: '${s.t('lang_om')} · ${s.t('lang_soon')}',
              selected: false,
              onTap: () => _soon(context, s.t('lang_om')),
            ),
          ],
        ),
      ],
    );
  }

  void _soon(BuildContext context, String lang) {
    final s = S.of(context);
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(s.t('lang_soon_msg', {'lang': lang}))),
    );
  }
}

class _LangChip extends StatelessWidget {
  const _LangChip(
      {required this.label, required this.selected, required this.onTap});

  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(999),
      child: Container(
        padding:
            const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        decoration: BoxDecoration(
          color: selected ? EthioColors.primary : Colors.white,
          borderRadius: BorderRadius.circular(999),
          border: Border.all(
              color:
                  selected ? EthioColors.primary : EthioColors.line),
        ),
        child: Text(label,
            style: TextStyle(
                fontSize: 14,
                fontWeight: FontWeight.w700,
                color: selected ? Colors.white : EthioColors.muted)),
      ),
    );
  }
}
