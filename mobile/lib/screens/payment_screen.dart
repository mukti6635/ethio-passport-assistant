import 'package:flutter/material.dart';

import '../data/service_catalog.dart';
import '../l10n/strings.dart';
import '../models/task.dart';
import '../state/task_store.dart';
import '../theme/ethio_theme.dart';
import '../widgets/core.dart';
import '../widgets/privacy_notice.dart';

/// Human approval: fee payment. Methods are Ethiopian-friendly (Telebirr,
/// Chapa, bank card). Fully simulated — no real charge.
class PaymentScreen extends StatefulWidget {
  const PaymentScreen({super.key, required this.taskId});

  final String taskId;

  @override
  State<PaymentScreen> createState() => _PaymentScreenState();
}

class _PaymentScreenState extends State<PaymentScreen> {
  int _method = 0;
  bool _processing = false;
  bool _success = false;

  static const _methods = [
    (Icons.phone_android_outlined, 'pay_telebirr', Color(0xFF1B7A43)),
    (Icons.account_balance_wallet_outlined, 'pay_chapa', Color(0xFF0B5CAD)),
    (Icons.credit_card_outlined, 'pay_card', Color(0xFF6A3FB5)),
  ];

  Future<void> _pay() async {
    setState(() => _processing = true);
    await Future<void>.delayed(const Duration(seconds: 2));
    if (!mounted) return;
    setState(() {
      _processing = false;
      _success = true;
    });
    final task = TaskStore.instance.taskById(widget.taskId)!;
    TaskStore.instance.approve(task, ApprovalKind.payment);
  }

  @override
  Widget build(BuildContext context) {
    final s = S.of(context);
    final task = TaskStore.instance.taskById(widget.taskId)!;
    final fee = serviceById(task.serviceId).feeLabel;
    return ScreenScaffold(
      title: s.t('pay_title'),
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const PrivacyNotice(
            titleKey: 'privacy_title',
            bodyKey: 'privacy_payment',
          ),
          const SizedBox(height: 16),
          if (!_success) ...[
            Card(
              color: Colors.white,
              elevation: 0,
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(20),
                side: const BorderSide(color: EthioColors.line),
              ),
              child: Padding(
                padding: const EdgeInsets.all(22),
                child: Column(
                  children: [
                    Text(s.t('pay_body'), style: EthioText.bodyMuted),
                    const SizedBox(height: 8),
                    Text(fee,
                        style: const TextStyle(
                            fontSize: 40,
                            fontWeight: FontWeight.w900,
                            color: EthioColors.primaryDark)),
                    const SizedBox(height: 4),
                    Text(task.title, style: EthioText.small),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 20),
            Text(s.t('pay_method'), style: EthioText.h3),
            const SizedBox(height: 10),
            for (var i = 0; i < _methods.length; i++)
              Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: InkWell(
                  onTap: _processing
                      ? null
                      : () => setState(() => _method = i),
                  borderRadius: BorderRadius.circular(16),
                  child: Container(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 18, vertical: 16),
                    decoration: BoxDecoration(
                      color: _method == i
                          ? EthioColors.primarySoft
                          : Colors.white,
                      borderRadius: BorderRadius.circular(16),
                      border: Border.all(
                        color: _method == i
                            ? EthioColors.primary
                            : EthioColors.line,
                        width: _method == i ? 2 : 1,
                      ),
                    ),
                    child: Row(
                      children: [
                        Container(
                          width: 46,
                          height: 46,
                          decoration: BoxDecoration(
                            color: _methods[i].$3.withValues(alpha: 0.14),
                            borderRadius: BorderRadius.circular(12),
                          ),
                          child: Icon(_methods[i].$1,
                              color: _methods[i].$3),
                        ),
                        const SizedBox(width: 14),
                        Expanded(
                          child: Text(s.t(_methods[i].$2),
                              style: const TextStyle(
                                  fontSize: 17,
                                  fontWeight: FontWeight.w700)),
                        ),
                        if (_method == i)
                          const Icon(Icons.check_circle,
                              color: EthioColors.primary),
                      ],
                    ),
                  ),
                ),
              ),
            const SizedBox(height: 8),
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: EthioColors.warnSoft,
                borderRadius: BorderRadius.circular(12),
              ),
              child: Row(
                children: [
                  const Icon(Icons.info_outline,
                      size: 18, color: EthioColors.warn),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(s.t('pay_demo'),
                        style: const TextStyle(
                            fontSize: 13,
                            fontWeight: FontWeight.w600,
                            color: EthioColors.warn)),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 16),
            _processing
                ? const Center(
                    child: Padding(
                      padding: EdgeInsets.all(16),
                      child: CircularProgressIndicator(),
                    ),
                  )
                : EthioButton(
                    label: s.t('pay_now', {'amount': fee}),
                    icon: Icons.lock_outline,
                    onPressed: _pay,
                  ),
          ] else ...[
            const SizedBox(height: 32),
            const Icon(Icons.check_circle,
                size: 96, color: EthioColors.ok),
            const SizedBox(height: 16),
            Text(s.t('pay_success'),
                textAlign: TextAlign.center, style: EthioText.h2),
            const SizedBox(height: 8),
            Text(
                '${s.t('pay_receipt')}: ${s.t(_methods[_method].$2)} · $fee',
                textAlign: TextAlign.center,
                style: EthioText.bodyMuted),
            const SizedBox(height: 24),
            EthioButton(
              label: s.t('common_done'),
              onPressed: () => Navigator.of(context).pop(),
            ),
          ],
        ],
      ),
    );
  }
}
