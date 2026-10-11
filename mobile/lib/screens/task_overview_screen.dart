import 'package:flutter/material.dart';

import '../data/service_catalog.dart';
import '../l10n/strings.dart';
import '../models/task.dart';
import '../state/task_store.dart';
import '../theme/ethio_theme.dart';
import '../widgets/core.dart';
import '../widgets/progress_header.dart';

/// Task overview: progress, next step, and entry points to every stage.
class TaskOverviewScreen extends StatelessWidget {
  const TaskOverviewScreen({super.key, required this.taskId});

  final String taskId;

  @override
  Widget build(BuildContext context) {
    final s = S.of(context);
    return ListenableBuilder(
      listenable: TaskStore.instance,
      builder: (context, _) {
        final task = TaskStore.instance.taskById(taskId);
        if (task == null) {
          return ScreenScaffold(
              title: 'ETHIO', body: const SizedBox.shrink());
        }
        final def = serviceById(task.serviceId);
        final next = task.nextAction(context);
        return ScreenScaffold(
          title: task.title,
          body: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              ProgressHeader(task: task),
              const SizedBox(height: 20),
              if (next != null) ...[
                _NextStepCard(
                  task: task,
                  label: s.t(next.labelKey, next.params),
                  onTap: () => Navigator.of(context)
                      .pushNamed(next.route, arguments: task.id),
                ),
                const SizedBox(height: 20),
              ],
              SectionTitle(title: s.t('ov_progress')),
              _StageList(task: task, defAccent: def.accent),
              const SizedBox(height: 8),
              InfoCard(
                icon: Icons.smart_toy_outlined,
                iconColor: EthioColors.primary,
                title: s.t('ai_title'),
                body: s.t('ai_sub'),
                onTap: () => Navigator.of(context)
                    .pushNamed('/ai', arguments: task.id),
              ),
            ],
          ),
        );
      },
    );
  }
}

class _NextStepCard extends StatelessWidget {
  const _NextStepCard(
      {required this.task, required this.label, required this.onTap});

  final ServiceTask task;
  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final s = S.of(context);
    return Card(
      color: EthioColors.primary,
      elevation: 0,
      shape:
          RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(20),
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(s.t('ov_next'),
                        style: const TextStyle(
                            color: EthioColors.white70,
                            fontSize: 14,
                            fontWeight: FontWeight.w600)),
                    const SizedBox(height: 4),
                    Text(label,
                        style: const TextStyle(
                            color: Colors.white,
                            fontSize: 19,
                            fontWeight: FontWeight.w800)),
                  ],
                ),
              ),
              Container(
                width: 52,
                height: 52,
                decoration: const BoxDecoration(
                  color: Colors.white,
                  shape: BoxShape.circle,
                ),
                child: const Icon(Icons.arrow_forward,
                    color: EthioColors.primary),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _StageList extends StatelessWidget {
  const _StageList({required this.task, required this.defAccent});

  final ServiceTask task;
  final Color defAccent;

  @override
  Widget build(BuildContext context) {
    final s = S.of(context);
    final entries = _entries(task);
    return Column(
      children: [
        for (final e in entries)
          Card(
            color: Colors.white,
            elevation: 0,
            margin: const EdgeInsets.only(bottom: 10),
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(16),
              side: const BorderSide(color: EthioColors.line),
            ),
            child: ListTile(
              contentPadding: const EdgeInsets.symmetric(
                  horizontal: 16, vertical: 6),
              leading: Container(
                width: 44,
                height: 44,
                decoration: BoxDecoration(
                  color: e.done
                      ? EthioColors.okSoft
                      : EthioColors.primarySoft,
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Icon(e.icon,
                    color:
                        e.done ? EthioColors.ok : EthioColors.primary),
              ),
              title: Text(s.t(e.titleKey),
                  style: const TextStyle(
                      fontWeight: FontWeight.w700, fontSize: 16)),
              subtitle: e.badge == null
                  ? null
                  : Padding(
                      padding: const EdgeInsets.only(top: 6),
                      child: StatusChip.warn(e.badge!),
                    ),
              trailing: e.done
                  ? const Icon(Icons.check_circle,
                      color: EthioColors.ok)
                  : const Icon(Icons.chevron_right,
                      color: EthioColors.muted),
              onTap: () => Navigator.of(context)
                  .pushNamed(e.route, arguments: task.id),
            ),
          ),
      ],
    );
  }

  List<_StageEntry> _entries(ServiceTask task) {
    final list = <_StageEntry>[
      _StageEntry('stage_requirements', Icons.list_alt_outlined,
          '/requirements', task.stage.index > TaskStage.requirements.index),
      _StageEntry('stage_documents', Icons.upload_file_outlined, '/upload',
          task.stage.index > TaskStage.documents.index),
      _StageEntry('stage_review', Icons.fact_check_outlined, '/review',
          task.stage.index > TaskStage.review.index),
      _StageEntry('stage_issues', Icons.report_problem_outlined, '/issues',
          task.stage.index > TaskStage.issues.index,
          badge: task.openIssues > 0 ? '${task.openIssues}' : null),
      _StageEntry('stage_approvals', Icons.verified_user_outlined,
          '/approvals', task.stage.index > TaskStage.approvals.index,
          badge:
              task.pendingApprovals > 0 ? '${task.pendingApprovals}' : null),
    ];
    final def = serviceById(task.serviceId);
    if (def.needsAppointment) {
      list.add(_StageEntry('stage_appointment', Icons.event_outlined,
          '/appointments', task.stage.index > TaskStage.appointment.index));
    }
    return list;
  }
}

class _StageEntry {
  _StageEntry(this.titleKey, this.icon, this.route, this.done, {this.badge});

  final String titleKey;
  final IconData icon;
  final String route;
  final bool done;
  final String? badge;
}
