import 'package:flutter/material.dart';

import '../l10n/strings.dart';
import '../models/task.dart';
import '../state/task_store.dart';
import '../theme/ethio_theme.dart';
import '../widgets/core.dart';

/// Missing-information and conflicting-data review. Each issue is resolved
/// inline; the flow continues only when everything is resolved.
class MissingInfoScreen extends StatelessWidget {
  const MissingInfoScreen({super.key, required this.taskId});

  final String taskId;

  @override
  Widget build(BuildContext context) {
    final s = S.of(context);
    return ListenableBuilder(
      listenable: TaskStore.instance,
      builder: (context, _) {
        final task = TaskStore.instance.taskById(taskId)!;
        final store = TaskStore.instance;
        final allResolved =
            task.issues.isNotEmpty && task.openIssues == 0;
        return ScreenScaffold(
          title: s.t('iss_title'),
          body: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(s.t('iss_sub'), style: EthioText.bodyMuted),
              const SizedBox(height: 16),
              for (final issue in task.issues)
                _IssueCard(
                  issue: issue,
                  onResolve: (value) =>
                      store.resolveIssue(task, issue.id, value),
                ),
              const SizedBox(height: 8),
              if (allResolved)
                Container(
                  padding: const EdgeInsets.all(14),
                  decoration: BoxDecoration(
                    color: EthioColors.okSoft,
                    borderRadius: BorderRadius.circular(14),
                  ),
                  child: Row(
                    children: [
                      const Icon(Icons.check_circle_outline,
                          color: EthioColors.ok),
                      const SizedBox(width: 10),
                      Expanded(
                        child: Text(s.t('iss_all_done'),
                            style: const TextStyle(
                                color: EthioColors.ok,
                                fontWeight: FontWeight.w600)),
                      ),
                    ],
                  ),
                ),
              const SizedBox(height: 12),
              EthioButton(
                label: s.t('iss_continue'),
                icon: Icons.arrow_forward,
                onPressed: allResolved
                    ? () {
                        store.advanceStage(task, TaskStage.approvals);
                        Navigator.of(context).pushNamed('/ai',
                            arguments: task.id);
                      }
                    : null,
              ),
            ],
          ),
        );
      },
    );
  }
}

class _IssueCard extends StatefulWidget {
  const _IssueCard({required this.issue, required this.onResolve});

  final IssueItem issue;
  final ValueChanged<String> onResolve;

  @override
  State<_IssueCard> createState() => _IssueCardState();
}

class _IssueCardState extends State<_IssueCard> {
  String? _picked;
  final _controller = TextEditingController();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final s = S.of(context);
    final issue = widget.issue;
    final isConflict = issue.kind == 'conflict';
    return Card(
      color: Colors.white,
      elevation: 0,
      margin: const EdgeInsets.only(bottom: 14),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(18),
        side: BorderSide(
          color: issue.resolved ? EthioColors.ok : EthioColors.warn,
          width: issue.resolved ? 1 : 1.6,
        ),
      ),
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                Container(
                  width: 44,
                  height: 44,
                  decoration: BoxDecoration(
                    color: issue.resolved
                        ? EthioColors.okSoft
                        : EthioColors.warnSoft,
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Icon(
                    issue.resolved
                        ? Icons.check
                        : isConflict
                            ? Icons.compare_arrows_outlined
                            : Icons.help_outline,
                    color: issue.resolved
                        ? EthioColors.ok
                        : EthioColors.warn,
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(issue.title, style: EthioText.smallBold),
                      const SizedBox(height: 2),
                      issue.resolved
                          ? StatusChip.ok(s.t('iss_resolved'),
                              icon: Icons.check)
                          : isConflict
                              ? StatusChip.warn(
                                  s.t('iss_conflict'),
                                  icon: Icons.compare_arrows_outlined)
                              : StatusChip.warn(s.t('iss_missing'),
                                  icon: Icons.help_outline),
                    ],
                  ),
                ),
              ],
            ),
            const SizedBox(height: 10),
            Text(issue.detail, style: EthioText.bodyMuted),
            if (!issue.resolved) ...[
              const SizedBox(height: 14),
              if (isConflict)
                ...issue.options.map((opt) => Padding(
                      padding: const EdgeInsets.only(bottom: 8),
                      child: InkWell(
                        onTap: () =>
                            setState(() => _picked = opt),
                        borderRadius: BorderRadius.circular(12),
                        child: Container(
                          padding: const EdgeInsets.symmetric(
                              horizontal: 16, vertical: 14),
                          decoration: BoxDecoration(
                            borderRadius: BorderRadius.circular(12),
                            border: Border.all(
                              color: _picked == opt
                                  ? EthioColors.primary
                                  : EthioColors.line,
                              width: _picked == opt ? 2 : 1,
                            ),
                            color: _picked == opt
                                ? EthioColors.primarySoft
                                : Colors.white,
                          ),
                          child: Row(
                            children: [
                              Expanded(
                                  child: Text(opt,
                                      style: const TextStyle(
                                          fontSize: 16,
                                          fontWeight:
                                              FontWeight.w600))),
                              if (_picked == opt)
                                const Icon(Icons.check_circle,
                                    color: EthioColors.primary),
                            ],
                          ),
                        ),
                      ),
                    )),
              if (!isConflict)
                TextField(
                  controller: _controller,
                  style: const TextStyle(fontSize: 17),
                  decoration: InputDecoration(
                      hintText: s.t('iss_type_fix')),
                  onChanged: (_) => setState(() {}),
                ),
              const SizedBox(height: 10),
              EthioButton(
                label: s.t('iss_save'),
                secondary: true,
                onPressed: _canSave ? () => _save() : null,
              ),
            ] else
              Padding(
                padding: const EdgeInsets.only(top: 10),
                child: Text(
                  '${s.t('iss_resolved')}: ${issue.resolution}',
                  style: const TextStyle(
                      fontWeight: FontWeight.w700,
                      color: EthioColors.ok),
                ),
              ),
          ],
        ),
      ),
    );
  }

  bool get _canSave {
    if (widget.issue.kind == 'conflict') return _picked != null;
    return _controller.text.trim().isNotEmpty;
  }

  void _save() {
    final value = widget.issue.kind == 'conflict'
        ? _picked!
        : _controller.text.trim();
    widget.onResolve(value);
  }
}
