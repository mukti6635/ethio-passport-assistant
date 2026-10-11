import 'package:flutter/material.dart';

import '../l10n/strings.dart';
import '../models/service.dart';
import '../models/task.dart';
import '../theme/ethio_theme.dart';

/// The complete service catalog. Every screen in the app renders from these
/// definitions — intake questions, requirement checklists, approval lists and
/// simulated AI steps. To add a service, add one [ServiceDefinition] here.
///
const List<ServiceDefinition> serviceCatalog = [
  ServiceDefinition(
    id: 'passport',
    titleKey: 'svc_passport',
    descKey: 'svc_passport_desc',
    icon: Icons.book_outlined,
    accent: EthioColors.primary,
    feeLabel: '600 ETB',
    needsAppointment: true,
    questions: [
      IntakeQuestion(
        id: 'purpose',
        labelKey: '_',
        type: QuestionType.choice,
        options: ['opt_new_passport', 'opt_renewal', 'opt_replacement'],
      ),
      IntakeQuestion(id: 'full_name', labelKey: '_', type: QuestionType.text),
      IntakeQuestion(id: 'dob', labelKey: '_', type: QuestionType.date),
      IntakeQuestion(id: 'phone', labelKey: '_', type: QuestionType.phone),
    ],
    requirements: [
      RequirementItem(
          id: 'national_id',
          labelKey: '_',
          descKey: '_',
          acceptedTypes: ['JPG', 'PNG', 'PDF']),
      RequirementItem(id: 'photo', labelKey: '_', descKey: '_'),
      RequirementItem(id: 'old_passport', labelKey: '_', descKey: '_'),
      RequirementItem(id: 'birth_cert', labelKey: '_', descKey: '_'),
    ],
    approvals: [ApprovalKind.otp, ApprovalKind.payment, ApprovalKind.legal],
    aiStepKeys: ['ai_step_check', 'ai_step_verify', 'ai_step_draft', 'ai_step_prepare'],
  ),
  ServiceDefinition(
    id: 'visa',
    titleKey: 'svc_visa',
    descKey: 'svc_visa_desc',
    icon: Icons.flight_outlined,
    accent: Color(0xFF0B5CAD),
    feeLabel: '1,200 ETB',
    questions: [
      IntakeQuestion(
        id: 'purpose',
        labelKey: '_',
        type: QuestionType.choice,
        options: ['opt_tourist', 'opt_business', 'opt_student', 'opt_transit'],
      ),
      IntakeQuestion(id: 'destination', labelKey: '_', type: QuestionType.text),
      IntakeQuestion(id: 'travel_date', labelKey: '_', type: QuestionType.date),
    ],
    requirements: [
      RequirementItem(id: 'passport_copy', labelKey: '_', descKey: '_'),
      RequirementItem(id: 'photo', labelKey: '_', descKey: '_'),
      RequirementItem(id: 'invitation', labelKey: '_', descKey: '_'),
    ],
    approvals: [ApprovalKind.otp, ApprovalKind.payment, ApprovalKind.legal],
    aiStepKeys: ['ai_step_check', 'ai_step_verify', 'ai_step_draft', 'ai_step_prepare'],
  ),
  ServiceDefinition(
    id: 'license',
    titleKey: 'svc_license',
    descKey: 'svc_license_desc',
    icon: Icons.badge_outlined,
    accent: Color(0xFF8A5A00),
    feeLabel: '350 ETB',
    needsAppointment: true,
    questions: [
      IntakeQuestion(
        id: 'purpose',
        labelKey: '_',
        type: QuestionType.choice,
        options: ['opt_new_license', 'opt_renewal'],
      ),
      IntakeQuestion(
        id: 'license_class',
        labelKey: '_',
        type: QuestionType.choice,
        options: ['opt_class_a', 'opt_class_b', 'opt_class_c'],
      ),
      IntakeQuestion(id: 'full_name', labelKey: '_', type: QuestionType.text),
    ],
    requirements: [
      RequirementItem(id: 'national_id', labelKey: '_', descKey: '_'),
      RequirementItem(id: 'medical', labelKey: '_', descKey: '_'),
      RequirementItem(id: 'photo', labelKey: '_', descKey: '_'),
    ],
    approvals: [
      ApprovalKind.otp,
      ApprovalKind.captcha,
      ApprovalKind.payment,
      ApprovalKind.legal
    ],
    aiStepKeys: ['ai_step_check', 'ai_step_verify', 'ai_step_draft', 'ai_step_prepare'],
  ),
  ServiceDefinition(
    id: 'certificates',
    titleKey: 'svc_certificates',
    descKey: 'svc_certificates_desc',
    icon: Icons.verified_outlined,
    accent: Color(0xFF6A3FB5),
    feeLabel: '200 ETB',
    questions: [
      IntakeQuestion(
        id: 'cert_type',
        labelKey: '_',
        type: QuestionType.choice,
        options: ['opt_birth_cert', 'opt_marriage_cert', 'opt_education'],
      ),
      IntakeQuestion(id: 'full_name', labelKey: '_', type: QuestionType.text),
    ],
    requirements: [
      RequirementItem(id: 'national_id', labelKey: '_', descKey: '_'),
      RequirementItem(id: 'support', labelKey: '_', descKey: '_'),
    ],
    approvals: [ApprovalKind.otp, ApprovalKind.payment, ApprovalKind.legal],
    aiStepKeys: ['ai_step_check', 'ai_step_verify', 'ai_step_draft', 'ai_step_prepare'],
  ),
  ServiceDefinition(
    id: 'business',
    titleKey: 'svc_business',
    descKey: 'svc_business_desc',
    icon: Icons.store_outlined,
    accent: Color(0xFFB3261E),
    feeLabel: '1,500 ETB',
    needsAppointment: true,
    questions: [
      IntakeQuestion(
        id: 'business_type',
        labelKey: '_',
        type: QuestionType.choice,
        options: ['opt_sole_prop', 'opt_plc', 'opt_cooperative'],
      ),
      IntakeQuestion(id: 'business_name', labelKey: '_', type: QuestionType.text),
      IntakeQuestion(id: 'phone', labelKey: '_', type: QuestionType.phone),
    ],
    requirements: [
      RequirementItem(id: 'national_id', labelKey: '_', descKey: '_'),
      RequirementItem(id: 'lease', labelKey: '_', descKey: '_'),
      RequirementItem(id: 'premises_photos', labelKey: '_', descKey: '_'),
    ],
    approvals: [ApprovalKind.otp, ApprovalKind.payment, ApprovalKind.legal],
    aiStepKeys: ['ai_step_check', 'ai_step_verify', 'ai_step_draft', 'ai_step_prepare'],
  ),
  ServiceDefinition(
    id: 'other',
    titleKey: 'svc_other',
    descKey: 'svc_other_desc',
    icon: Icons.grid_view_outlined,
    accent: EthioColors.muted,
    feeLabel: '—',
    questions: [
      IntakeQuestion(id: 'describe', labelKey: '_', type: QuestionType.text),
    ],
    requirements: [
      RequirementItem(id: 'national_id', labelKey: '_', descKey: '_'),
    ],
    approvals: [ApprovalKind.otp, ApprovalKind.legal],
    aiStepKeys: ['ai_step_check', 'ai_step_draft', 'ai_step_prepare'],
  ),
];

ServiceDefinition serviceById(String id) => serviceCatalog.firstWhere(
      (s) => s.id == id,
      orElse: () => serviceCatalog.last,
    );

/// Human-readable prototype labels for catalog fields whose labelKey is '_'.
/// (Keeps the catalog free of hard-coded UI strings while staying simple.)
/// Resolve a catalog display label through localization.
///
/// [kind] is 'question', 'requirement' or 'requirement_desc'; [id] is the
/// catalog id (e.g. 'full_name'). Returns the translated label, falling back
/// to English per key via [S.t].
String catalogLabel(S s, String serviceId, String kind, String id) {
  switch (kind) {
    case 'question':
      return s.t({
            'purpose': 'q_purpose',
            'full_name': 'q_full_name',
            'dob': 'q_dob',
            'phone': 'q_phone',
            'destination': 'q_destination',
            'travel_date': 'q_travel_date',
            'license_class': 'q_license_class',
            'cert_type': 'q_cert_type',
            'business_type': 'q_business_type',
            'business_name': 'q_business_name',
            'describe': 'q_describe',
          }[id] ??
          id);
    case 'requirement':
      return s.t({
            'national_id': 'r_national_id',
            'photo': 'r_photo',
            'old_passport': 'r_old_passport',
            'birth_cert': 'r_birth_cert',
            'passport_copy': 'r_passport_copy',
            'invitation': 'r_invitation',
            'medical': 'r_medical',
            'support': 'r_support',
            'lease': 'r_lease',
            'premises_photos': 'r_premises_photos',
          }[id] ??
          id);
    case 'requirement_desc':
      return s.t({
            'national_id': 'r_national_id_d',
            'photo': 'r_photo_d',
            'old_passport': 'r_old_passport_d',
            'birth_cert': 'r_birth_cert_d',
            'passport_copy': 'r_passport_copy_d',
            'invitation': 'r_invitation_d',
            'medical': 'r_medical_d',
            'support': 'r_support_d',
            'lease': 'r_lease_d',
            'premises_photos': 'r_premises_photos_d',
          }[id] ??
          '');
    default:
      return id;
  }
}
