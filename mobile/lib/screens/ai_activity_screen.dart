import 'dart:async';

import 'package:flutter/material.dart';

import '../integrations/browser_use_client.dart';
import '../l10n/strings.dart';
import '../models/task.dart';
import '../state/task_store.dart';
import '../theme/ethio_theme.dart';
import '../widgets/core.dart';

/// AI activity + task status: a live timeline of the agent's steps.
/// The browser-automation backend plugs in here later via
/// [BrowserUseClient]; until then the timeline is a labeled simulation.
class AiActivityScreen extends StatefulWidget {
  const AiActivityScreen({super.key, required this.taskId});

  final String taskId;

  @override
  State<AiActivityScreen> createState() => _AiActivityScreenState();
}

class _AiActivityScreenState extends State<AiActivityScreen> {
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    // Simulate the agent working through its steps, two seconds apart.
    _timer = Timer.periodic(const Duration(seconds: 2), (_) {
      final task = TaskStore.instance.taskById(widget.taskId);
      if (task == null) {
        _timer?.cancel();
        return;
      }
      final more = TaskStore.instance.advanceAiStep(task);
      if (!more) _timer?.cancel();
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final s = S.of(context);
    return ListenableBuilder(
      listenable: TaskStore.instance,
      builder: (context, _) {
        final task = TaskStore.instance.taskById(widget.taskId)!;
        final store = TaskStore.instance;
        final allDone = task.aiSteps.isNotEmpty &&
            task.aiSteps.every((e) => e.status == AiStepStatus.done);
        return ScreenScaffold(
          title: s.t('ai_title'),
          body: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(s.t('ai_sub'), style: EthioText.bodyMuted),
              const SizedBox(height: 12),
              Container(
                padding: const EdgeInsets.all(14),
                decoration: BoxDecoration(
                  color: EthioColors.infoSoft,
                  borderRadius: BorderRadius.circular(14),
                ),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Icon(Icons.cloud_off_outlined,
                        color: EthioColors.info, size: 22),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text(s.t('ai_not_connected'),
                          style: const TextStyle(
                              fontSize: 14,
                              color: EthioColors.info,
                              height: 1.4)),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 18),
              for (var i = 0; i < task.aiSteps.length; i++)
                _StepRow(step: task.aiSteps[i], last: i == task.aiSteps.length - 1),
              const SizedBox(height: 16),
              EthioButton(
                label: s.t('ai_continue'),
                icon: Icons.arrow_forward,
                onPressed: allDone
                    ? () {
                        store.advanceStage(task, TaskStage.approvals);
                        Navigator.of(context).pushNamed('/approvals',
                            arguments: task.id);
                      }
                    : null,
              ),
              if (!allDone)
                Padding(
                  padding: const EdgeInsets.only(top: 12),
                  child: Text(s.t('ai_wait_msg'),
                      textAlign: TextAlign.center,
                      style: EthioText.small),
                ),
            ],
          ),
        );
      },
    );
  }
}

class _StepRow extends StatelessWidget {
  const _StepRow({required this.step, required this.last});

  final AiStep step;
  final bool last;

  @override
  Widget build(BuildContext context) {
    final s = S.of(context);
    final Color color;
    final Widget icon;
    final String status;
    switch (step.status) {
      case AiStepStatus.done:
        color = EthioColors.ok;
        icon = const Icon(Icons.check_circle,
            color: EthioColors.ok, size: 28);
        status = s.t('ai_done');
        break;
      case AiStepStatus.running:
        color = EthioColors.primary;
        icon = const SizedBox(
          width: 28,
          height: 28,
          child: CircularProgressIndicator(
              strokeWidth: 3, color: EthioColors.primary),
        );
        status = s.t('ai_running');
        break;
      case AiStepStatus.waiting:
        color = EthioColors.muted;
        icon = const Icon(Icons.radio_button_unchecked,
            color: EthioColors.muted, size: 28);
        status = s.t('ai_waiting');
        break;
    }
    return IntrinsicHeight(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Column(
            children: [
              icon,
              if (!last)
                Expanded(
                  child: Container(
                    width: 2,
                    margin: const EdgeInsets.symmetric(vertical: 4),
                    color: step.status == AiStepStatus.done
                        ? EthioColors.ok
                        : EthioColors.line,
                  ),
                ),
            ],
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Padding(
              padding: EdgeInsets.only(bottom: last ? 0 : 20),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(s.t(step.labelKey),
                      style: TextStyle(
                          fontSize: 17,
                          fontWeight: FontWeight.w700,
                          color: step.status == AiStepStatus.waiting
                              ? EthioColors.muted
                              : EthioColors.ink)),
                  const SizedBox(height: 2),
                  Text(status,
                      style: TextStyle(
                          fontSize: 14,
                          fontWeight: FontWeight.w600,
                          color: color)),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}
