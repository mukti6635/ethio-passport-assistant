import 'package:flutter/material.dart';

import '../data/service_catalog.dart';
import '../l10n/strings.dart';
import '../models/task.dart';
import '../state/task_store.dart';
import '../theme/ethio_theme.dart';
import '../widgets/cards.dart';
import '../widgets/core.dart';

/// Dynamic requirements checklist, rendered from the service catalog.
class RequirementsScreen extends StatelessWidget {
  const RequirementsScreen({super.key, required this.taskId});

  final String taskId;

  @override
  Widget build(BuildContext context) {
    final s = S.of(context);
    return ListenableBuilder(
      listenable: TaskStore.instance,
      builder: (context, _) {
        final task = TaskStore.instance.taskById(taskId)!;
        final def = serviceById(task.serviceId);
        final readyCount = def.requirements
            .where((r) =>
                task.docs.any((d) => d.requirementId == r.id))
            .length;
        return ScreenScaffold(
          title: s.t('req_title'),
          body: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(s.t('req_sub'), style: EthioText.bodyMuted),
              const SizedBox(height: 6),
              Text('$readyCount / ${def.requirements.length} ${s.t('req_ready').toLowerCase()}',
                  style: EthioText.smallBold),
              const SizedBox(height: 16),
              for (final req in def.requirements)
                RequirementTile(
                  title: catalogLabel(
                      s, task.serviceId, 'requirement', req.id),
                  subtitle: catalogLabel(
                      s, task.serviceId, 'requirement_desc', req.id),
                  typesLabel: s.t('req_types',
                      {'types': req.acceptedTypes.join(', ')}),
                  done: task.docs
                      .any((d) => d.requirementId == req.id),
                  onTap: () => Navigator.of(context)
                      .pushNamed('/upload', arguments: task.id),
                ),
              const SizedBox(height: 8),
              EthioButton(
                label: s.t('common_continue'),
                icon: Icons.arrow_forward,
                onPressed: readyCount == 0
                    ? null
                    : () {
                        TaskStore.instance
                            .advanceStage(task, TaskStage.documents);
                        Navigator.of(context).pushNamed('/upload',
                            arguments: task.id);
                      },
              ),
              if (readyCount == 0)
                Padding(
                  padding: const EdgeInsets.only(top: 12),
                  child: Text(
                    s.t('req_sub'),
                    textAlign: TextAlign.center,
                    style: EthioText.small,
                  ),
                ),
            ],
          ),
        );
      },
    );
  }
}
