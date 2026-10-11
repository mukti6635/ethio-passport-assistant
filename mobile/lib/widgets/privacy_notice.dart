import 'package:flutter/material.dart';

import '../l10n/strings.dart';
import '../theme/ethio_theme.dart';

/// Inline privacy notice shown before sensitive actions (uploads, payments,
/// final legal review). It is deliberately *not* a blocking dialog: the user
/// taps "I understand" inline to acknowledge, and the rest of the screen
/// keeps working whether or not they have tapped yet.
class PrivacyNotice extends StatefulWidget {
  const PrivacyNotice({
    super.key,
    required this.titleKey,
    required this.bodyKey,
  });

  /// Localization key for the notice title.
  final String titleKey;

  /// Localization key for the plain-language explanation.
  final String bodyKey;

  @override
  State<PrivacyNotice> createState() => _PrivacyNoticeState();
}

class _PrivacyNoticeState extends State<PrivacyNotice> {
  bool _acknowledged = false;

  @override
  Widget build(BuildContext context) {
    final s = S.of(context);
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: EthioColors.primarySoft,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: EthioColors.primary, width: 1.2),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Icon(Icons.privacy_tip_outlined,
                  color: EthioColors.primary, size: 24),
              const SizedBox(width: 12),
              Expanded(
                child: Text(s.t(widget.titleKey),
                    style: const TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.w800,
                        color: EthioColors.ink)),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(s.t(widget.bodyKey),
              style: const TextStyle(
                  fontSize: 14, color: EthioColors.ink, height: 1.5)),
          const SizedBox(height: 12),
          _acknowledged
              ? Row(
                  children: [
                    const Icon(Icons.check_circle,
                        color: EthioColors.ok, size: 20),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(s.t('privacy_acknowledged'),
                          style: const TextStyle(
                              fontSize: 14,
                              fontWeight: FontWeight.w700,
                              color: EthioColors.ok)),
                    ),
                  ],
                )
              : SizedBox(
                  width: double.infinity,
                  child: OutlinedButton.icon(
                    onPressed: () =>
                        setState(() => _acknowledged = true),
                    style: OutlinedButton.styleFrom(
                      minimumSize: const Size(0, 48),
                      foregroundColor: EthioColors.primary,
                      side: const BorderSide(
                          color: EthioColors.primary, width: 1.6),
                      shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(14)),
                    ),
                    icon: const Icon(Icons.check_outlined, size: 20),
                    label: Text(s.t('privacy_ack'),
                        style: const TextStyle(
                            fontSize: 15,
                            fontWeight: FontWeight.w700)),
                  ),
                ),
        ],
      ),
    );
  }
}
