import 'package:flutter/material.dart';

import '../l10n/strings.dart';
import '../models/task.dart';
import '../theme/ethio_theme.dart';

/// Horizontal stage stepper + progress bar for a task.
class ProgressHeader extends StatelessWidget {
  const ProgressHeader({super.key, required this.task});

  final ServiceTask task;

  static const _stageKeys = [
    'stage_intake',
    'stage_requirements',
    'stage_documents',
    'stage_review',
    'stage_issues',
    'stage_approvals',
    'stage_appointment',
    'stage_done',
  ];

  @override
  Widget build(BuildContext context) {
    final s = S.of(context);
    final current = task.stage.index;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text(s.t('ov_progress'), style: EthioText.smallBold),
            Text('${(task.progress * 100).round()}%',
                style: const TextStyle(
                    fontSize: 14,
                    fontWeight: FontWeight.w800,
                    color: EthioColors.primary)),
          ],
        ),
        const SizedBox(height: 8),
        ClipRRect(
          borderRadius: BorderRadius.circular(999),
          child: LinearProgressIndicator(
            value: task.progress,
            minHeight: 10,
            backgroundColor: EthioColors.primary12,
            valueColor:
                const AlwaysStoppedAnimation<Color>(EthioColors.primary),
          ),
        ),
        const SizedBox(height: 16),
        SizedBox(
          height: 88,
          child: ListView.separated(
            scrollDirection: Axis.horizontal,
            itemCount: _stageKeys.length,
            separatorBuilder: (_, __) => const SizedBox(width: 4),
            itemBuilder: (context, i) {
              final done = i < current;
              final isCurrent = i == current;
              final color = done || isCurrent
                  ? EthioColors.primary
                  : EthioColors.muted;
              final bg = isCurrent
                  ? EthioColors.primary
                  : done
                      ? EthioColors.okSoft
                      : EthioColors.bg;
              return Column(
                children: [
                  Container(
                    width: 40,
                    height: 40,
                    decoration: BoxDecoration(
                      color: bg,
                      shape: BoxShape.circle,
                      border: Border.all(
                        color: isCurrent
                            ? EthioColors.primary
                            : EthioColors.line,
                        width: 2,
                      ),
                    ),
                    child: Icon(
                      done
                          ? Icons.check
                          : isCurrent
                              ? Icons.radio_button_checked
                              : Icons.circle_outlined,
                      size: 20,
                      color: isCurrent ? Colors.white : color,
                    ),
                  ),
                  const SizedBox(height: 6),
                  SizedBox(
                    width: 72,
                    child: Text(
                      s.t(_stageKeys[i]),
                      textAlign: TextAlign.center,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                        fontSize: 11,
                        fontWeight:
                            isCurrent ? FontWeight.w800 : FontWeight.w600,
                        color: color,
                      ),
                    ),
                  ),
                ],
              );
            },
          ),
        ),
      ],
    );
  }
}
