import 'package:flutter/material.dart';

import 'task.dart';

/// A kind of question the generic intake flow can render.
/// New services reuse these — no service-specific screens are needed.
enum QuestionType { choice, text, phone, date }

class IntakeQuestion {
  const IntakeQuestion({
    required this.id,
    required this.labelKey,
    this.hintKey,
    required this.type,
    this.options = const [],
  });

  final String id;
  final String labelKey;
  final String? hintKey;
  final QuestionType type;

  /// For [QuestionType.choice]: option label keys shown as chips.
  final List<String> options;
}

/// One required document for a service.
class RequirementItem {
  const RequirementItem({
    required this.id,
    required this.labelKey,
    required this.descKey,
    this.acceptedTypes = const ['PDF', 'JPG', 'PNG'],
  });

  final String id;
  final String labelKey;
  final String descKey;
  final List<String> acceptedTypes;
}

/// Declarative description of a government service.
///
/// The whole app is driven by these definitions: the intake flow, the
/// requirements checklist, the approval list and the simulated AI steps all
/// render from here. Adding a new service = adding one entry in
/// [serviceCatalog] — no new screens, no hard-coded workflows.
class ServiceDefinition {
  const ServiceDefinition({
    required this.id,
    required this.titleKey,
    required this.descKey,
    required this.icon,
    required this.accent,
    required this.questions,
    required this.requirements,
    required this.approvals,
    required this.aiStepKeys,
    required this.feeLabel,
    this.needsAppointment = false,
  });

  final String id;
  final String titleKey;
  final String descKey;
  final IconData icon;
  final Color accent;
  final List<IntakeQuestion> questions;
  final List<RequirementItem> requirements;

  /// Human approvals this service needs, in order.
  final List<ApprovalKind> approvals;

  /// Label keys for the simulated AI worker steps.
  final List<String> aiStepKeys;

  /// Display fee, e.g. '600 ETB'. Prototype display value only.
  final String feeLabel;
  final bool needsAppointment;
}
