import 'package:flutter/material.dart';

import '../data/service_catalog.dart';
import '../l10n/strings.dart';
import '../models/task.dart';
import '../state/task_store.dart';
import '../theme/ethio_theme.dart';
import '../widgets/cards.dart';
import '../widgets/core.dart';
import '../widgets/privacy_notice.dart';

/// Document upload: per-requirement slots with preview thumbnails and
/// removal. Prototype uses generated sample files — never real documents.
class UploadScreen extends StatelessWidget {
  const UploadScreen({super.key, required this.taskId});

  final String taskId;

  @override
  Widget build(BuildContext context) {
    final s = S.of(context);
    return ListenableBuilder(
      listenable: TaskStore.instance,
      builder: (context, _) {
        final task = TaskStore.instance.taskById(taskId)!;
        final def = serviceById(task.serviceId);
        final store = TaskStore.instance;
        return ScreenScaffold(
          title: s.t('up_title'),
          body: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const PrivacyNotice(
                titleKey: 'privacy_title',
                bodyKey: 'privacy_upload',
              ),
              const SizedBox(height: 16),
              Container(
                padding: const EdgeInsets.all(14),
                decoration: BoxDecoration(
                  color: EthioColors.infoSoft,
                  borderRadius: BorderRadius.circular(14),
                ),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Icon(Icons.info_outline,
                        color: EthioColors.info, size: 22),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text(s.t('up_sample_note'),
                          style: const TextStyle(
                              fontSize: 14,
                              color: EthioColors.info,
                              height: 1.4)),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 18),
              for (final req in def.requirements) ...[
                SectionTitle(
                  title: catalogLabel(
                      s, task.serviceId, 'requirement', req.id),
                  action: TextButton.icon(
                    onPressed: () => store.addSampleDoc(task, req.id),
                    icon: const Icon(Icons.add, size: 20),
                    label: Text(s.t('up_add')),
                  ),
                ),
                ...task.docs
                    .where((d) => d.requirementId == req.id)
                    .map((doc) => DocumentCard(
                          doc: doc,
                          onRemove: () =>
                              _confirmRemove(context, task, doc),
                        )),
                if (!task.docs
                    .any((d) => d.requirementId == req.id))
                  Padding(
                    padding: const EdgeInsets.only(bottom: 16),
                    child: Text(s.t('up_empty'),
                        style: EthioText.small),
                  ),
              ],
              const SizedBox(height: 12),
              EthioButton(
                label: s.t('up_continue'),
                icon: Icons.arrow_forward,
                onPressed: task.docs.isEmpty
                    ? null
                    : () {
                        store.runExtraction(task);
                        store.advanceStage(task, TaskStage.review);
                        Navigator.of(context).pushNamed('/review',
                            arguments: task.id);
                      },
              ),
            ],
          ),
        );
      },
    );
  }

  void _confirmRemove(
      BuildContext context, ServiceTask task, DocItem doc) {
    final s = S.of(context);
    showDialog<void>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(s.t('up_remove_title')),
        content:
            Text(s.t('up_remove_body', {'name': doc.fileName})),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: Text(s.t('common_cancel')),
          ),
          TextButton(
            onPressed: () {
              TaskStore.instance.removeDoc(task, doc.id);
              Navigator.of(context).pop();
            },
            child: Text(s.t('up_remove'),
                style: const TextStyle(color: EthioColors.danger)),
          ),
        ],
      ),
    );
  }
}
