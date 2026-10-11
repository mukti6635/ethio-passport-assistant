import 'package:flutter/material.dart';

/// The generic pipeline every service task moves through.
enum TaskStage {
  intake,
  requirements,
  documents,
  review,
  issues,
  approvals,
  appointment,
  done,
}

/// Kinds of human approval. Rendered by the generic approval hub.
enum ApprovalKind { otp, captcha, payment, legal }

enum ApprovalStatus { pending, approved }

enum AiStepStatus { waiting, running, done }

/// A document attached to a task. In this prototype documents are simulated
/// samples — never real identity documents.
class DocItem {
  DocItem({
    required this.id,
    required this.requirementId,
    required this.labelKey,
    required this.fileName,
    required this.fileType,
    required this.sizeKb,
    this.sample = true,
  });

  final String id;
  final String requirementId;
  final String labelKey;
  final String fileName;
  final String fileType;
  final int sizeKb;
  final bool sample;
}

/// A field "read" from the documents, shown for user correction.
class ExtractedField {
  ExtractedField({
    required this.id,
    required this.labelKey,
    required this.value,
    required this.confidence,
    this.edited = false,
  });

  final String id;
  final String labelKey;
  String value;
  final double confidence; // 0..1
  bool edited;
}

/// Something the AI cannot resolve alone.
class IssueItem {
  IssueItem({
    required this.id,
    required this.kind, // 'missing' or 'conflict'
    required this.title,
    required this.detail,
    this.options = const [],
    this.resolution,
  });

  final String id;
  final String kind;
  final String title;
  final String detail;

  /// For conflicts: candidate values the user picks between.
  final List<String> options;
  String? resolution;

  bool get resolved => resolution != null && resolution!.isNotEmpty;
}

class ApprovalItem {
  ApprovalItem({required this.kind, this.status = ApprovalStatus.pending});

  final ApprovalKind kind;
  ApprovalStatus status;

  bool get approved => status == ApprovalStatus.approved;
}

class AiStep {
  AiStep({required this.labelKey, this.status = AiStepStatus.waiting});

  final String labelKey;
  AiStepStatus status;
  DateTime? finishedAt;
}

class AppointmentInfo {
  AppointmentInfo({
    required this.office,
    required this.dayLabel,
    required this.timeLabel,
    required this.reference,
  });

  final String office;
  final String dayLabel;
  final String timeLabel;
  final String reference;
}

/// One user task, e.g. "Passport renewal". All screens render from this.
class ServiceTask {
  ServiceTask({
    required this.id,
    required this.serviceId,
    required this.title,
    required this.createdAt,
    this.stage = TaskStage.requirements,
    Map<String, String>? answers,
    List<DocItem>? docs,
    List<ExtractedField>? fields,
    List<IssueItem>? issues,
    List<ApprovalItem>? approvals,
    List<AiStep>? aiSteps,
    this.appointment,
  })  : answers = answers ?? {},
        docs = docs ?? [],
        fields = fields ?? [],
        issues = issues ?? [],
        approvals = approvals ?? [],
        aiSteps = aiSteps ?? [];

  final String id;
  final String serviceId;
  final String title;
  final DateTime createdAt;
  TaskStage stage;
  final Map<String, String> answers;
  final List<DocItem> docs;
  final List<ExtractedField> fields;
  final List<IssueItem> issues;
  final List<ApprovalItem> approvals;
  final List<AiStep> aiSteps;
  AppointmentInfo? appointment;

  bool get isDone => stage == TaskStage.done;

  int get openIssues => issues.where((i) => !i.resolved).length;
  int get pendingApprovals =>
      approvals.where((a) => !a.approved).length;

  /// Overall progress 0..1 derived from stage plus sub-step completion.
  double get progress {
    final total = TaskStage.values.length - 1;
    var p = stage.index / total;
    // Nudge the bar within a stage so it feels alive.
    switch (stage) {
      case TaskStage.documents:
        p += 0.0;
        break;
      case TaskStage.issues:
        if (issues.isNotEmpty) {
          p += (issues.where((i) => i.resolved).length / issues.length) *
              (1 / total) *
              0.8;
        }
        break;
      case TaskStage.approvals:
        if (approvals.isNotEmpty) {
          p += (approvals.where((a) => a.approved).length / approvals.length) *
              (1 / total) *
              0.8;
        }
        break;
      default:
        break;
    }
    return p.clamp(0.0, 1.0);
  }

  /// Route + label for the single next action, or null when done.
  ({String route, String labelKey, Map<String, String>? params})? nextAction(
      BuildContext context) {
    switch (stage) {
      case TaskStage.intake:
      case TaskStage.requirements:
        return (route: '/requirements', labelKey: 'next_requirements', params: null);
      case TaskStage.documents:
        return (route: '/upload', labelKey: 'next_documents', params: null);
      case TaskStage.review:
        return (route: '/review', labelKey: 'next_review', params: null);
      case TaskStage.issues:
        return (
          route: '/issues',
          labelKey: 'next_issues',
          params: {'n': '$openIssues'}
        );
      case TaskStage.approvals:
        return (
          route: '/approvals',
          labelKey: 'next_approvals',
          params: {'n': '$pendingApprovals'}
        );
      case TaskStage.appointment:
        return (route: '/appointments', labelKey: 'next_appointment', params: null);
      case TaskStage.done:
        return null;
    }
  }
}
