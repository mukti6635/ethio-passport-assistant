import 'package:flutter/material.dart';

import '../l10n/strings.dart';
import '../models/task.dart';
import '../theme/ethio_theme.dart';
import 'core.dart';

/// Service tile on the home screen: big touch target, icon, title, subtitle.
class ServiceCard extends StatelessWidget {
  const ServiceCard({
    super.key,
    required this.icon,
    required this.accent,
    required this.title,
    required this.subtitle,
    required this.onTap,
  });

  final IconData icon;
  final Color accent;
  final String title;
  final String subtitle;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Card(
      color: Colors.white,
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(20),
        side: const BorderSide(color: EthioColors.line),
      ),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(20),
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Container(
                width: 48,
                height: 48,
                decoration: BoxDecoration(
                  color: accent.withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(16),
                ),
                child: Icon(icon, color: accent, size: 26),
              ),
              const SizedBox(height: 10),
              Text(title,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                      fontSize: 15,
                      fontWeight: FontWeight.w800,
                      color: EthioColors.ink)),
              const SizedBox(height: 2),
              Text(subtitle,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: EthioText.small),
            ],
          ),
        ),
      ),
    );
  }
}

/// One row of the requirements checklist.
class RequirementTile extends StatelessWidget {
  const RequirementTile({
    super.key,
    required this.title,
    required this.subtitle,
    required this.typesLabel,
    required this.done,
    required this.onTap,
  });

  final String title;
  final String subtitle;
  final String typesLabel;
  final bool done;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final s = S.of(context);
    return Card(
      color: Colors.white,
      elevation: 0,
      margin: const EdgeInsets.only(bottom: 12),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(18),
        side: const BorderSide(color: EthioColors.line),
      ),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(18),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Row(
            children: [
              Container(
                width: 46,
                height: 46,
                decoration: BoxDecoration(
                  color: done ? EthioColors.okSoft : EthioColors.bg,
                  shape: BoxShape.circle,
                ),
                child: Icon(
                  done ? Icons.check : Icons.upload_file_outlined,
                  color: done ? EthioColors.ok : EthioColors.muted,
                  size: 24,
                ),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(title, style: EthioText.smallBold),
                    const SizedBox(height: 2),
                    Text(subtitle, style: EthioText.small),
                    const SizedBox(height: 6),
                    done
                        ? StatusChip.ok(s.t('req_ready'), icon: Icons.check)
                        : StatusChip.warn(s.t('req_missing'),
                            icon: Icons.pending_outlined),
                  ],
                ),
              ),
              const SizedBox(width: 8),
              const Icon(Icons.chevron_right, color: EthioColors.muted),
            ],
          ),
        ),
      ),
    );
  }
}

/// Document preview card with thumbnail and remove button.
class DocumentCard extends StatelessWidget {
  const DocumentCard({
    super.key,
    required this.doc,
    required this.onRemove,
    this.onTap,
  });

  final DocItem doc;
  final VoidCallback onRemove;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final s = S.of(context);
    return Card(
      color: Colors.white,
      elevation: 0,
      margin: const EdgeInsets.only(bottom: 12),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(18),
        side: const BorderSide(color: EthioColors.line),
      ),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(18),
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Row(
            children: [
              _Thumbnail(doc: doc),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(doc.fileName,
                        style: EthioText.smallBold,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis),
                    const SizedBox(height: 4),
                    Text('${doc.fileType} · ${doc.sizeKb} KB',
                        style: EthioText.caption),
                    if (doc.sample) ...[
                      const SizedBox(height: 6),
                      StatusChip.info(s.t('up_sample'),
                          icon: Icons.science_outlined),
                    ],
                  ],
                ),
              ),
              IconButton(
                tooltip: s.t('up_remove'),
                icon: const Icon(Icons.delete_outline,
                    color: EthioColors.danger),
                onPressed: onRemove,
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Generated placeholder thumbnail (no downloaded images — low bandwidth).
class _Thumbnail extends StatelessWidget {
  const _Thumbnail({required this.doc});

  final DocItem doc;

  @override
  Widget build(BuildContext context) {
    final isPdf = doc.fileType == 'PDF';
    return Container(
      width: 64,
      height: 80,
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(10),
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: isPdf
              ? [const Color(0xFFD66A5A), const Color(0xFFA83A2C)]
              : [const Color(0xFF5FA88F), const Color(0xFF0B6B4F)],
        ),
      ),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          const Icon(Icons.description_outlined,
              color: Colors.white, size: 24),
          const SizedBox(height: 4),
          Text(doc.fileType,
              style: const TextStyle(
                  color: Colors.white,
                  fontSize: 12,
                  fontWeight: FontWeight.w800)),
        ],
      ),
    );
  }
}

/// Task row used by My Tasks and History.
class TaskCard extends StatelessWidget {
  const TaskCard({
    super.key,
    required this.task,
    required this.accent,
    required this.serviceTitle,
    required this.actionLabel,
    required this.onTap,
  });

  final ServiceTask task;
  final Color accent;
  final String serviceTitle;
  final String actionLabel;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final s = S.of(context);
    return Card(
      color: Colors.white,
      elevation: 0,
      margin: const EdgeInsets.only(bottom: 12),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(18),
        side: const BorderSide(color: EthioColors.line),
      ),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(18),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(task.title,
                        style: const TextStyle(
                            fontSize: 17,
                            fontWeight: FontWeight.w800,
                            color: EthioColors.ink)),
                  ),
                  task.isDone
                      ? StatusChip.ok(s.t('status_complete'),
                          icon: Icons.check_circle_outline)
                      : StatusChip.info(s.t('status_in_progress'),
                          icon: Icons.timelapse_outlined),
                ],
              ),
              const SizedBox(height: 4),
              Text(serviceTitle, style: EthioText.small),
              const SizedBox(height: 12),
              ClipRRect(
                borderRadius: BorderRadius.circular(999),
                child: LinearProgressIndicator(
                  value: task.progress,
                  minHeight: 8,
                  backgroundColor: EthioColors.bg,
                  valueColor:
                      AlwaysStoppedAnimation<Color>(accent),
                ),
              ),
              const SizedBox(height: 12),
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text(
                      '${(task.progress * 100).round()}% · ${s.t('ov_created', {'date': _shortDate(task.createdAt)})}',
                      style: EthioText.caption),
                  TextButton(
                    onPressed: onTap,
                    child: Text(actionLabel),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  static String _shortDate(DateTime d) =>
      '${d.year}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';
}
