import 'package:flutter/material.dart';

import '../data/service_catalog.dart';
import '../l10n/strings.dart';
import '../state/task_store.dart';
import '../theme/ethio_theme.dart';
import '../widgets/cards.dart';
import '../widgets/core.dart';

/// History tab: finished tasks with resume functionality.
class HistoryScreen extends StatelessWidget {
  const HistoryScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final s = S.of(context);
    return Scaffold(
      appBar: AppBar(title: Text(s.t('tab_history'))),
      body: SafeArea(
        child: Column(
          children: [
            const PrototypeBanner(),
            Expanded(
              child: ListenableBuilder(
                listenable: TaskStore.instance,
                builder: (context, _) {
                  final tasks = TaskStore.instance.doneTasks;
                  if (tasks.isEmpty) {
                    return SingleChildScrollView(
                      padding: const EdgeInsets.all(20),
                      child: EmptyState(
                        icon: Icons.history_outlined,
                        message: s.t('hist_empty'),
                      ),
                    );
                  }
                  return ListView.builder(
                    padding: const EdgeInsets.all(20),
                    itemCount: tasks.length,
                    itemBuilder: (context, i) {
                      final task = tasks[i];
                      final def = serviceById(task.serviceId);
                      return Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          TaskCard(
                            task: task,
                            accent: def.accent,
                            serviceTitle: s.t(def.titleKey),
                            actionLabel: s.t('hist_resume'),
                            onTap: () => Navigator.of(context)
                                .pushNamed('/task',
                                    arguments: task.id),
                          ),
                          if (task.appointment != null)
                            Padding(
                              padding:
                                  const EdgeInsets.only(bottom: 16),
                              child: Container(
                                padding: const EdgeInsets.all(14),
                                decoration: BoxDecoration(
                                  color: EthioColors.okSoft,
                                  borderRadius:
                                      BorderRadius.circular(14),
                                ),
                                child: Row(
                                  children: [
                                    const Icon(
                                        Icons.event_available_outlined,
                                        color: EthioColors.ok),
                                    const SizedBox(width: 10),
                                    Expanded(
                                      child: Text(
                                        '${task.appointment!.dayLabel} · ${task.appointment!.timeLabel} · ${task.appointment!.office}',
                                        style: const TextStyle(
                                            fontSize: 14,
                                            fontWeight: FontWeight.w600,
                                            color: EthioColors.ok),
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                            ),
                        ],
                      );
                    },
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }
}
