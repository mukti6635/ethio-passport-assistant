import 'package:flutter/material.dart';

import '../l10n/strings.dart';
import '../theme/ethio_theme.dart';

/// App bar + safe area + optional prototype banner, shared by all screens.
class ScreenScaffold extends StatelessWidget {
  const ScreenScaffold({
    super.key,
    required this.title,
    required this.body,
    this.actions,
    this.showBanner = true,
    this.bottomBar,
    this.scrollable = true,
  });

  final String title;
  final Widget body;
  final List<Widget>? actions;
  final bool showBanner;
  final Widget? bottomBar;
  final bool scrollable;

  @override
  Widget build(BuildContext context) {
    final content = Padding(
      padding: const EdgeInsets.fromLTRB(20, 16, 20, 24),
      child: body,
    );
    return Scaffold(
      appBar: AppBar(title: Text(title), actions: actions),
      bottomNavigationBar: bottomBar,
      body: SafeArea(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            if (showBanner) const PrototypeBanner(),
            Expanded(
              child: scrollable
                  ? SingleChildScrollView(child: content)
                  : content,
            ),
          ],
        ),
      ),
    );
  }
}

/// Slim banner reminding the user this is a prototype.
class PrototypeBanner extends StatelessWidget {
  const PrototypeBanner({super.key});

  @override
  Widget build(BuildContext context) {
    final s = S.of(context);
    return Container(
      color: EthioColors.warnSoft,
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 10),
      child: Row(
        children: [
          const Icon(Icons.science_outlined,
              size: 18, color: EthioColors.warn),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              s.t('prototype_banner'),
              style: const TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                  color: EthioColors.warn),
            ),
          ),
        ],
      ),
    );
  }
}

/// Big, thumb-friendly primary button.
class EthioButton extends StatelessWidget {
  const EthioButton({
    super.key,
    required this.label,
    required this.onPressed,
    this.icon,
    this.secondary = false,
    this.danger = false,
  });

  final String label;
  final VoidCallback? onPressed;
  final IconData? icon;
  final bool secondary;
  final bool danger;

  @override
  Widget build(BuildContext context) {
    final child = Row(
      mainAxisAlignment: MainAxisAlignment.center,
      mainAxisSize: MainAxisSize.min,
      children: [
        if (icon != null) ...[
          Icon(icon, size: 22),
          const SizedBox(width: 10),
        ],
        Flexible(
          child: Text(label,
              textAlign: TextAlign.center,
              style: const TextStyle(fontSize: 17)),
        ),
      ],
    );
    final style = secondary
        ? OutlinedButton.styleFrom(
            foregroundColor:
                danger ? EthioColors.danger : EthioColors.primary,
            side: BorderSide(
                color: danger ? EthioColors.danger : EthioColors.primary,
                width: 1.6),
          )
        : danger
            ? ElevatedButton.styleFrom(
                backgroundColor: EthioColors.danger,
                foregroundColor: Colors.white,
              )
            : null;
    final button = secondary
        ? OutlinedButton(
            onPressed: onPressed, style: style, child: child)
        : ElevatedButton(onPressed: onPressed, style: style, child: child);
    return SizedBox(width: double.infinity, child: button);
  }
}

/// Section heading with optional trailing action.
class SectionTitle extends StatelessWidget {
  const SectionTitle({super.key, required this.title, this.action});

  final String title;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 8, bottom: 12),
      child: Row(
        children: [
          Expanded(child: Text(title, style: EthioText.h3)),
          if (action != null) action!,
        ],
      ),
    );
  }
}

/// Small rounded status pill.
class StatusChip extends StatelessWidget {
  const StatusChip({
    super.key,
    required this.label,
    required this.color,
    required this.softColor,
    this.icon,
  });

  final String label;
  final Color color;
  final Color softColor;
  final IconData? icon;

  factory StatusChip.ok(String label, {IconData? icon}) => StatusChip(
      label: label,
      color: EthioColors.ok,
      softColor: EthioColors.okSoft,
      icon: icon);
  factory StatusChip.warn(String label, {IconData? icon}) => StatusChip(
      label: label,
      color: EthioColors.warn,
      softColor: EthioColors.warnSoft,
      icon: icon);
  factory StatusChip.info(String label, {IconData? icon}) => StatusChip(
      label: label,
      color: EthioColors.info,
      softColor: EthioColors.infoSoft,
      icon: icon);
  factory StatusChip.danger(String label, {IconData? icon}) => StatusChip(
      label: label,
      color: EthioColors.danger,
      softColor: EthioColors.dangerSoft,
      icon: icon);

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
      decoration: BoxDecoration(
        color: softColor,
        borderRadius: BorderRadius.circular(999),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (icon != null) ...[
            Icon(icon, size: 15, color: color),
            const SizedBox(width: 6),
          ],
          Text(label,
              style: TextStyle(
                  fontSize: 13, fontWeight: FontWeight.w700, color: color)),
        ],
      ),
    );
  }
}

/// Icon + title + body information card.
class InfoCard extends StatelessWidget {
  const InfoCard({
    super.key,
    required this.icon,
    required this.iconColor,
    required this.title,
    required this.body,
    this.onTap,
  });

  final IconData icon;
  final Color iconColor;
  final String title;
  final String body;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    return Card(
      color: Colors.white,
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(20),
        side: const BorderSide(color: EthioColors.line),
      ),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(20),
        child: Padding(
          padding: const EdgeInsets.all(18),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                width: 48,
                height: 48,
                decoration: BoxDecoration(
                  color: EthioColors.primarySoft,
                  borderRadius: BorderRadius.circular(14),
                ),
                child: Icon(icon, color: iconColor, size: 26),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(title, style: EthioText.h3),
                    const SizedBox(height: 4),
                    Text(body, style: EthioText.bodyMuted),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Friendly empty state.
class EmptyState extends StatelessWidget {
  const EmptyState(
      {super.key, required this.icon, required this.message});

  final IconData icon;
  final String message;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 48),
      child: Column(
        children: [
          Container(
            width: 88,
            height: 88,
            decoration: const BoxDecoration(
              color: EthioColors.primarySoft,
              shape: BoxShape.circle,
            ),
            child: Icon(icon, size: 40, color: EthioColors.primary),
          ),
          const SizedBox(height: 16),
          Text(message,
              textAlign: TextAlign.center, style: EthioText.bodyMuted),
        ],
      ),
    );
  }
}

/// Bottom padding helper so content never hides behind a bottom bar.
class BottomPad extends StatelessWidget {
  const BottomPad({super.key, this.height = 96});

  final double height;

  @override
  Widget build(BuildContext context) => SizedBox(height: height);
}
