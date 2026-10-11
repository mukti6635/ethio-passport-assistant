import 'package:flutter/material.dart';

import '../data/service_catalog.dart';
import '../l10n/strings.dart';
import '../state/task_store.dart';
import '../widgets/cards.dart';
import '../widgets/core.dart';

/// My Tasks tab: all active (non-finished) tasks with resume.
class TasksScreen extends StatelessWidget {
  const TasksScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final s = S.of(context);
    return Scaffold(
      appBar: AppBar(title: Text(s.t('tab_tasks'))),
      body: SafeArea(
        child: Column(
          children: [
            const PrototypeBanner(),
            Expanded(
              child: ListenableBuilder(
                listenable: TaskStore.instance,
                builder: (context, _) {
                  final tasks = TaskStore.instance.activeTasks;
                  if (tasks.isEmpty) {
                    return SingleChildScrollView(
                      padding: const EdgeInsets.all(20),
                      child: EmptyState(
                        icon: Icons.assignment_outlined,
                        message: s.t('tasks_empty'),
                      ),
                    );
                  }
                  return ListView.builder(
                    padding: const EdgeInsets.all(20),
                    itemCount: tasks.length,
                    itemBuilder: (context, i) {
                      final task = tasks[i];
                      final def = serviceById(task.serviceId);
                      return TaskCard(
                        task: task,
                        accent: def.accent,
                        serviceTitle: s.t(def.titleKey),
                        actionLabel: s.t('hist_resume'),
                        onTap: () => Navigator.of(context)
                            .pushNamed('/task', arguments: task.id),
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
