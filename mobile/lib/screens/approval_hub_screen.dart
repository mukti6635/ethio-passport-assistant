import 'package:flutter/material.dart';

import '../l10n/strings.dart';
import '../models/task.dart';
import '../state/task_store.dart';
import '../theme/ethio_theme.dart';
import '../widgets/core.dart';

/// Human approval hub: OTP, CAPTCHA, payments and the final legal step.
/// The AI never passes these without the user.
class ApprovalHubScreen extends StatelessWidget {
  const ApprovalHubScreen({super.key, required this.taskId});

  final String taskId;

  @override
  Widget build(BuildContext context) {
    final s = S.of(context);
    return ListenableBuilder(
      listenable: TaskStore.instance,
      builder: (context, _) {
        final task = TaskStore.instance.taskById(taskId)!;
        final store = TaskStore.instance;
        final allApproved = task.approvals.isNotEmpty &&
            task.approvals.every((a) => a.approved);
        return ScreenScaffold(
          title: s.t('ap_title'),
          body: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(s.t('ap_sub'), style: EthioText.bodyMuted),
              const SizedBox(height: 16),
              for (final approval in task.approvals)
                _ApprovalTile(
                  approval: approval,
                  onTap: approval.approved
                      ? null
                      : () => Navigator.of(context).pushNamed(
                          _routeFor(approval.kind),
                          arguments: task.id),
                ),
              const SizedBox(height: 12),
              Container(
                padding: const EdgeInsets.all(14),
                decoration: BoxDecoration(
                  color: EthioColors.bg,
                  borderRadius: BorderRadius.circular(14),
                  border: Border.all(color: EthioColors.line),
                ),
                child: Text(s.t('ap_hint'), style: EthioText.small),
              ),
              const SizedBox(height: 16),
              EthioButton(
                label: s.t('common_continue'),
                icon: Icons.arrow_forward,
                onPressed: allApproved
                    ? () {
                        final def = _defFor(task);
                        if (def) {
                          store.advanceStage(task, TaskStage.appointment);
                          Navigator.of(context).pushNamed('/appointments',
                              arguments: task.id);
                        } else {
                          store.finishWithoutAppointment(task);
                          Navigator.of(context).pushNamedAndRemoveUntil(
                              '/', (r) => false);
                        }
                      }
                    : null,
              ),
            ],
          ),
        );
      },
    );
  }

  String _routeFor(ApprovalKind kind) {
    switch (kind) {
      case ApprovalKind.otp:
        return '/otp';
      case ApprovalKind.captcha:
        return '/captcha';
      case ApprovalKind.payment:
        return '/payment';
      case ApprovalKind.legal:
        return '/legal';
    }
  }

  bool _defFor(ServiceTask task) {
    // Only services that need an in-person visit go to appointments.
    const needs = {'passport', 'license', 'business'};
    return needs.contains(task.serviceId);
  }
}

class _ApprovalTile extends StatelessWidget {
  const _ApprovalTile({required this.approval, required this.onTap});

  final ApprovalItem approval;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final s = S.of(context);
    final meta = _meta(approval.kind);
    return Card(
      color: Colors.white,
      elevation: 0,
      margin: const EdgeInsets.only(bottom: 12),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(18),
        side: const BorderSide(color: EthioColors.line),
      ),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(18),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Row(
            children: [
              Container(
                width: 52,
                height: 52,
                decoration: BoxDecoration(
                  color: approval.approved
                      ? EthioColors.okSoft
                      : EthioColors.primarySoft,
                  borderRadius: BorderRadius.circular(14),
                ),
                child: Icon(meta.$1,
                    color: approval.approved
                        ? EthioColors.ok
                        : EthioColors.primary,
                    size: 28),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(meta.$2, style: EthioText.smallBold),
                    const SizedBox(height: 4),
                    approval.approved
                        ? StatusChip.ok(s.t('ap_approved'),
                            icon: Icons.check)
                        : StatusChip.warn(s.t('ap_pending'),
                            icon: Icons.hourglass_empty_outlined),
                  ],
                ),
              ),
              if (!approval.approved)
                TextButton(
                  onPressed: onTap,
                  child: Text(s.t('ap_open')),
                )
              else
                const Icon(Icons.check_circle,
                    color: EthioColors.ok),
            ],
          ),
        ),
      ),
    );
  }

  (IconData, String) _meta(ApprovalKind kind) {
    switch (kind) {
      case ApprovalKind.otp:
        return (Icons.sms_outlined, 'Verification code');
      case ApprovalKind.captcha:
        return (Icons.shield_outlined, 'Security check');
      case ApprovalKind.payment:
        return (Icons.payments_outlined, 'Payment');
      case ApprovalKind.legal:
        return (Icons.gavel_outlined, 'Final legal review');
    }
  }
}
