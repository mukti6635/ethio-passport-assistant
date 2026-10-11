import 'package:flutter/material.dart';

import '../data/service_catalog.dart';
import '../l10n/strings.dart';
import '../models/task.dart';
import '../state/task_store.dart';
import '../theme/ethio_theme.dart';
import '../widgets/core.dart';
import '../widgets/privacy_notice.dart';

/// Final legal review. The user reads a summary and ticks consent boxes.
///
/// IMPORTANT: the submit button is deliberately disabled in this prototype —
/// ETHIO must never claim a government application was submitted without
/// verified evidence, and this build has no government integration at all.
class LegalScreen extends StatefulWidget {
  const LegalScreen({super.key, required this.taskId});

  final String taskId;

  @override
  State<LegalScreen> createState() => _LegalScreenState();
}

class _LegalScreenState extends State<LegalScreen> {
  final _checks = [false, false, false];
  String? _error;

  @override
  Widget build(BuildContext context) {
    final s = S.of(context);
    final task = TaskStore.instance.taskById(widget.taskId)!;
    final def = serviceById(task.serviceId);
    final allChecked = _checks.every((c) => c);
    return ScreenScaffold(
      title: s.t('legal_title'),
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const PrivacyNotice(
            titleKey: 'privacy_title',
            bodyKey: 'privacy_legal',
          ),
          const SizedBox(height: 16),
          Text(s.t('legal_body'), style: EthioText.bodyMuted),
          const SizedBox(height: 16),
          Card(
            color: Colors.white,
            elevation: 0,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(18),
              side: const BorderSide(color: EthioColors.line),
            ),
            child: Padding(
              padding: const EdgeInsets.all(18),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(s.t(def.titleKey), style: EthioText.h3),
                  const SizedBox(height: 12),
                  for (final e in task.answers.entries)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 8),
                      child: Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          SizedBox(
                            width: 140,
                            child: Text(
                              catalogLabel(
                                  s, task.serviceId, 'question', e.key),
                              style: EthioText.small,
                            ),
                          ),
                          Expanded(
                            child: Text(e.value,
                                style: EthioText.smallBold),
                          ),
                        ],
                      ),
                    ),
                  for (final f in task.fields)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 8),
                      child: Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          SizedBox(
                              width: 140,
                              child: Text(f.labelKey,
                                  style: EthioText.small)),
                          Expanded(
                              child: Text(f.value,
                                  style: EthioText.smallBold)),
                        ],
                      ),
                    ),
                  Padding(
                    padding: const EdgeInsets.only(top: 4),
                    child: Text(
                        '${task.docs.length} documents attached (samples)',
                        style: EthioText.small),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 16),
          for (var i = 0; i < 3; i++)
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: InkWell(
                onTap: () =>
                    setState(() => _checks[i] = !_checks[i]),
                borderRadius: BorderRadius.circular(14),
                child: Container(
                  padding: const EdgeInsets.all(14),
                  decoration: BoxDecoration(
                    color: Colors.white,
                    borderRadius: BorderRadius.circular(14),
                    border: Border.all(color: EthioColors.line),
                  ),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Checkbox(
                        value: _checks[i],
                        activeColor: EthioColors.primary,
                        onChanged: (v) => setState(
                            () => _checks[i] = v ?? false),
                      ),
                      Expanded(
                        child: Padding(
                          padding:
                              const EdgeInsets.only(top: 12),
                          child: Text(
                              s.t('legal_c${i + 1}'),
                              style: const TextStyle(
                                  fontSize: 15, height: 1.4)),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          if (_error != null) ...[
            const SizedBox(height: 4),
            Text(_error!,
                style: const TextStyle(
                    color: EthioColors.danger,
                    fontWeight: FontWeight.w600)),
          ],
          const SizedBox(height: 12),
          Container(
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(
              color: EthioColors.dangerSoft,
              borderRadius: BorderRadius.circular(14),
            ),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Icon(Icons.lock_outline,
                    color: EthioColors.danger),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(s.t('legal_locked'),
                      style: const TextStyle(
                          fontSize: 14,
                          color: EthioColors.danger,
                          fontWeight: FontWeight.w600,
                          height: 1.45)),
                ),
              ],
            ),
          ),
          const SizedBox(height: 16),
          // Disabled on purpose: no submission without a real integration.
          EthioButton(
            label: s.t('legal_submit'),
            icon: Icons.send_outlined,
            onPressed: null,
          ),
          const SizedBox(height: 10),
          EthioButton(
            label: s.t('legal_finish'),
            secondary: true,
            onPressed: () {
              if (!allChecked) {
                setState(
                    () => _error = s.t('legal_check_all'));
                return;
              }
              TaskStore.instance
                  .approve(task, ApprovalKind.legal);
              Navigator.of(context).pop();
            },
          ),
        ],
      ),
    );
  }
}
