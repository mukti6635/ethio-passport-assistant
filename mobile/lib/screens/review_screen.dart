import 'package:flutter/material.dart';

import '../l10n/strings.dart';
import '../models/task.dart';
import '../state/task_store.dart';
import '../theme/ethio_theme.dart';
import '../widgets/core.dart';

/// Extracted-information review: shows what the AI "read" from the documents
/// with confidence bars; every field is user-correctable.
class ReviewScreen extends StatelessWidget {
  const ReviewScreen({super.key, required this.taskId});

  final String taskId;

  @override
  Widget build(BuildContext context) {
    final s = S.of(context);
    return ListenableBuilder(
      listenable: TaskStore.instance,
      builder: (context, _) {
        final task = TaskStore.instance.taskById(taskId)!;
        final store = TaskStore.instance;
        return ScreenScaffold(
          title: s.t('rev_title'),
          body: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(s.t('rev_sub'), style: EthioText.bodyMuted),
              const SizedBox(height: 6),
              Row(
                children: [
                  const Icon(Icons.auto_awesome,
                      size: 16, color: EthioColors.primary),
                  const SizedBox(width: 6),
                  Expanded(
                    child: Text(s.t('rev_auto'), style: EthioText.caption),
                  ),
                ],
              ),
              const SizedBox(height: 16),
              for (final field in task.fields)
                _FieldCard(
                  field: field,
                  onEdit: () =>
                      _editField(context, task, field),
                ),
              const SizedBox(height: 12),
              EthioButton(
                label: s.t('rev_confirm'),
                icon: Icons.arrow_forward,
                onPressed: () {
                  store.advanceStage(task, TaskStage.issues);
                  Navigator.of(context)
                      .pushNamed('/issues', arguments: task.id);
                },
              ),
            ],
          ),
        );
      },
    );
  }

  void _editField(
      BuildContext context, ServiceTask task, ExtractedField field) {
    final s = S.of(context);
    final controller = TextEditingController(text: field.value);
    showDialog<void>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('${s.t('rev_edit')}: ${field.labelKey}'),
        content: TextField(
          controller: controller,
          autofocus: true,
          style: const TextStyle(fontSize: 18),
          decoration: const InputDecoration(),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: Text(s.t('common_cancel')),
          ),
          TextButton(
            onPressed: () {
              TaskStore.instance
                  .updateField(task, field.id, controller.text.trim());
              Navigator.of(context).pop();
            },
            child: Text(s.t('rev_save')),
          ),
        ],
      ),
    );
  }
}

class _FieldCard extends StatelessWidget {
  const _FieldCard({required this.field, required this.onEdit});

  final ExtractedField field;
  final VoidCallback onEdit;

  @override
  Widget build(BuildContext context) {
    final s = S.of(context);
    final pct = (field.confidence * 100).round();
    final confColor = field.confidence >= 0.9
        ? EthioColors.ok
        : field.confidence >= 0.8
            ? EthioColors.warn
            : EthioColors.danger;
    return Card(
      color: Colors.white,
      elevation: 0,
      margin: const EdgeInsets.only(bottom: 12),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(18),
        side: const BorderSide(color: EthioColors.line),
      ),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(field.labelKey,
                      style: EthioText.caption),
                ),
                if (field.edited)
                  StatusChip.info(s.t('rev_edited'),
                      icon: Icons.edit_outlined),
              ],
            ),
            const SizedBox(height: 4),
            Row(
              children: [
                Expanded(
                  child: Text(field.value,
                      style: const TextStyle(
                          fontSize: 18,
                          fontWeight: FontWeight.w700,
                          color: EthioColors.ink)),
                ),
                TextButton.icon(
                  onPressed: onEdit,
                  icon: const Icon(Icons.edit_outlined, size: 18),
                  label: Text(s.t('rev_edit')),
                ),
              ],
            ),
            const SizedBox(height: 8),
            Row(
              children: [
                Text('${s.t('rev_confidence')}: $pct%',
                    style: EthioText.caption),
                const SizedBox(width: 10),
                Expanded(
                  child: ClipRRect(
                    borderRadius: BorderRadius.circular(999),
                    child: LinearProgressIndicator(
                      value: field.confidence,
                      minHeight: 6,
                      backgroundColor: EthioColors.bg,
                      valueColor:
                          AlwaysStoppedAnimation<Color>(confColor),
                    ),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
