/// Universal agent engine for ETHIO.
///
/// A deterministic state machine that plans the next step of any service task
/// through the OBSERVE -> UNDERSTAND -> REASON -> ACT -> VERIFY loop.
///
/// Design rules:
/// * Fully generic: driven only by [ServiceDefinition] (from
///   `lib/data/service_catalog.dart`) and the runtime [ServiceTask] state.
///   There are no service-specific classes or branches anywhere in this file.
/// * Deterministic: state transitions come from [transitionTable], a fixed
///   table of guard rules — never from AI whims. The same snapshot always
///   produces the same plan.
/// * The engine is a pure planner: it never mutates the task. It returns an
///   [AgentPlan]; the UI / store decides whether to execute it.
/// * Human checkpoints (OTP, CAPTCHA, payment, legal review, appointment
///   booking) are enforced IN CODE: [planNext] refuses to plan a transition
///   past a checkpoint without an explicit recorded [UserAuthorization], and
///   [verifyPlan] re-checks every proposed plan a second time. A plan that
///   somehow slips through is downgraded to "blocked" instead of advancing.
library;

import '../data/service_catalog.dart';
import '../models/service.dart';
import '../models/task.dart';

// ---------------------------------------------------------------------------
// Phases
// ---------------------------------------------------------------------------

/// The five phases of one agent cycle, in order.
enum AgentPhase { observe, understand, reason, act, verify }

// ---------------------------------------------------------------------------
// Checkpoints & authorizations
// ---------------------------------------------------------------------------

/// Every point where the agent must stop and wait for the human.
/// Mirrors [ApprovalKind] plus appointment booking, which is not an approval
/// but still needs the user's explicit say-so.
enum CheckpointKind { otp, captcha, payment, legal, appointmentBooking }

/// Map an approval kind from the service catalog to its checkpoint kind.
CheckpointKind checkpointForApproval(ApprovalKind kind) {
  switch (kind) {
    case ApprovalKind.otp:
      return CheckpointKind.otp;
    case ApprovalKind.captcha:
      return CheckpointKind.captcha;
    case ApprovalKind.payment:
      return CheckpointKind.payment;
    case ApprovalKind.legal:
      return CheckpointKind.legal;
  }
}

/// An explicit, recorded user authorization to pass one checkpoint.
///
/// Created when the user completes a checkpoint screen (OTP entered, CAPTCHA
/// solved, payment confirmed, legal review accepted, appointment booked).
/// The engine only trusts these records — never assumptions.
class UserAuthorization {
  UserAuthorization({
    required this.checkpoint,
    this.grantedBy = 'user',
    DateTime? recordedAt,
  }) : recordedAt = recordedAt ?? DateTime.now();

  final CheckpointKind checkpoint;

  /// Who granted it: 'user' for a real human action, anything else is
  /// treated as untrusted by convention (the engine only checks presence,
  /// the *recording* of these must happen at the real checkpoint screens).
  final String grantedBy;
  final DateTime recordedAt;
}

// ---------------------------------------------------------------------------
// Snapshot: everything the engine knows about one task, right now
// ---------------------------------------------------------------------------

/// A read-only, derived view of a task used for planning. Built fresh on
/// every cycle from the [ServiceTask], its [ServiceDefinition], and the
/// recorded authorizations — so planning always sees current state.
class AgentSnapshot {
  AgentSnapshot._({
    required this.task,
    required this.definition,
    required this.authorizations,
  })  : answersComplete = definition.questions.every(
            (q) => (task.answers[q.id]?.trim().isNotEmpty ?? false)),
        allDocsUploaded = definition.requirements
            .every((r) => task.docs.any((d) => d.requirementId == r.id)),
        extractionDone = task.fields.isNotEmpty,
        noOpenIssues = task.openIssues == 0,
        allApprovalsApproved = task.approvals.every((a) => a.approved),
        appointmentBooked = task.appointment != null;

  factory AgentSnapshot.fromTask(
    ServiceTask task,
    List<UserAuthorization> authorizations,
  ) {
    return AgentSnapshot._(
      task: task,
      definition: serviceById(task.serviceId),
      authorizations: List.unmodifiable(authorizations),
    );
  }

  final ServiceTask task;
  final ServiceDefinition definition;
  final List<UserAuthorization> authorizations;

  /// Derived readiness flags (UNDERSTAND phase).
  final bool answersComplete;
  final bool allDocsUploaded;
  final bool extractionDone;
  final bool noOpenIssues;
  final bool allApprovalsApproved;
  final bool appointmentBooked;

  /// Checkpoints the user has explicitly authorized.
  Set<CheckpointKind> get authorizedCheckpoints =>
      authorizations.map((a) => a.checkpoint).toSet();

  bool isAuthorized(CheckpointKind kind) =>
      authorizedCheckpoints.contains(kind);
}

// ---------------------------------------------------------------------------
// Transition table: the deterministic heart of the engine
// ---------------------------------------------------------------------------

/// One row of the transition table: from one stage, under a guard, to the
/// next stage — listing which human checkpoints that move crosses.
class TransitionRule {
  TransitionRule({
    required this.from,
    required this.to,
    required this.guard,
    required this.checkpoints,
    required this.rationale,
  });

  final TaskStage from;
  final TaskStage to;

  /// True when the task is ready for this move.
  final bool Function(AgentSnapshot s) guard;

  /// Checkpoints crossed by this move. ALL must be authorized first.
  final List<CheckpointKind> Function(AgentSnapshot s) checkpoints;

  /// Human-readable reason, used in the plan's rationale.
  final String rationale;
}

/// The complete, fixed transition table. Same snapshot in -> same plan out.
final List<TransitionRule> transitionTable = [
  TransitionRule(
    from: TaskStage.intake,
    to: TaskStage.requirements,
    guard: (s) => s.answersComplete,
    checkpoints: (_) => const [],
    rationale: 'Intake answers are complete; show the requirements checklist.',
  ),
  TransitionRule(
    from: TaskStage.requirements,
    to: TaskStage.documents,
    guard: (_) => true,
    checkpoints: (_) => const [],
    rationale: 'Requirements shown; collect the required documents.',
  ),
  TransitionRule(
    from: TaskStage.documents,
    to: TaskStage.review,
    guard: (s) => s.allDocsUploaded,
    checkpoints: (_) => const [],
    rationale: 'Every requirement has a document; review the extracted info.',
  ),
  TransitionRule(
    from: TaskStage.review,
    to: TaskStage.issues,
    guard: (s) => s.extractionDone,
    checkpoints: (_) => const [],
    rationale: 'Fields extracted from documents; resolve open issues.',
  ),
  TransitionRule(
    from: TaskStage.issues,
    to: TaskStage.approvals,
    guard: (s) => s.noOpenIssues,
    // Entering approvals does not itself cross a checkpoint; the checkpoints
    // are crossed when LEAVING approvals (see below), after the user has
    // actually completed each checkpoint screen.
    checkpoints: (_) => const [],
    rationale: 'All issues resolved; collect the human approvals.',
  ),
  TransitionRule(
    from: TaskStage.approvals,
    to: TaskStage.appointment,
    guard: (s) => s.allApprovalsApproved,
    // HARD GATE: every approval this service needs (OTP, CAPTCHA, payment,
    // final legal review) must have an explicit recorded authorization.
    checkpoints: (s) =>
        s.definition.approvals.map(checkpointForApproval).toList(),
    rationale:
        'All approvals granted by the user; proceed to appointment booking.',
  ),
  TransitionRule(
    from: TaskStage.appointment,
    to: TaskStage.done,
    guard: (s) => s.appointmentBooked,
    // HARD GATE: booking the appointment itself needs the user's say-so.
    checkpoints: (_) => const [CheckpointKind.appointmentBooking],
    rationale: 'Appointment is booked and confirmed by the user; task done.',
  ),
];

// ---------------------------------------------------------------------------
// Plans
// ---------------------------------------------------------------------------

/// What the engine proposes to do next.
enum AgentAction {
  /// Move the task to [AgentPlan.targetStage].
  advanceStage,

  /// Blocked: waiting on one or more human checkpoints. See [AgentPlan.blockedBy].
  requestAuthorization,

  /// No rule matched: waiting on the user to provide input first.
  waitForInput,

  /// Task is finished; nothing left to plan.
  finished,
}

/// The engine's output: the next action plus the rationale behind it.
class AgentPlan {
  const AgentPlan({
    required this.action,
    this.targetStage,
    required this.rationale,
    this.blockedBy = const [],
    this.phaseTrace = const [],
    this.checkpointViolated = false,
  });

  final AgentAction action;
  final TaskStage? targetStage;

  /// Why this action was chosen (REASON phase, human-readable).
  final String rationale;

  /// Checkpoints still missing authorization, when blocked.
  final List<CheckpointKind> blockedBy;

  /// One line per phase of the cycle that produced this plan.
  final List<String> phaseTrace;

  /// True when VERIFY had to stop an unsafe plan. Such plans never advance.
  final bool checkpointViolated;

  bool get isBlocked => action == AgentAction.requestAuthorization;

  AgentPlan copyWith({
    AgentAction? action,
    TaskStage? targetStage,
    String? rationale,
    List<CheckpointKind>? blockedBy,
    List<String>? phaseTrace,
    bool? checkpointViolated,
  }) {
    return AgentPlan(
      action: action ?? this.action,
      targetStage: targetStage ?? this.targetStage,
      rationale: rationale ?? this.rationale,
      blockedBy: blockedBy ?? this.blockedBy,
      phaseTrace: phaseTrace ?? this.phaseTrace,
      checkpointViolated: checkpointViolated ?? this.checkpointViolated,
    );
  }

  @override
  String toString() =>
      'AgentPlan(action: $action, target: $targetStage, blockedBy: $blockedBy)';
}

// ---------------------------------------------------------------------------
// The engine
// ---------------------------------------------------------------------------

/// Plans the next step for any service task. Pure: never mutates the task.
class AgentEngine {
  /// Observe + Understand + Reason + Act, then Verify.
  ///
  /// Returns the next action and the rationale, with a per-phase trace.
  AgentPlan planNext({
    required ServiceTask task,
    required List<UserAuthorization> authorizations,
  }) {
    final snapshot = AgentSnapshot.fromTask(task, authorizations);
    return runCycle(snapshot);
  }

  /// Run one full OBSERVE -> UNDERSTAND -> REASON -> ACT -> VERIFY cycle
  /// over a snapshot.
  AgentPlan runCycle(AgentSnapshot s) {
    final trace = <String>[];

    // OBSERVE: gather raw facts.
    trace.add(
      'OBSERVE: stage=${s.task.stage.name}, docs=${s.task.docs.length}, '
      'fields=${s.task.fields.length}, openIssues=${s.task.openIssues}, '
      'approvals=${s.task.approvals.where((a) => a.approved).length}/${s.task.approvals.length}, '
      'authorized=${s.authorizedCheckpoints.map((c) => c.name).join(",")}',
    );

    // UNDERSTAND: derive readiness flags.
    trace.add(
      'UNDERSTAND: answersComplete=${s.answersComplete}, '
      'allDocsUploaded=${s.allDocsUploaded}, extractionDone=${s.extractionDone}, '
      'noOpenIssues=${s.noOpenIssues}, allApprovalsApproved=${s.allApprovalsApproved}, '
      'appointmentBooked=${s.appointmentBooked}',
    );

    // REASON: apply the transition table.
    final rule = _matchingRule(s);
    trace.add(
      'REASON: ${rule == null ? 'no transition rule matched' : 'matched ${rule.from.name} -> ${rule.to.name}: ${rule.rationale}'}',
    );

    // ACT: propose the plan (checkpoint gate applied here, first check).
    var plan = _propose(s, rule);
    trace.add(
      'ACT: proposed action=${plan.action.name}'
      '${plan.targetStage == null ? '' : ' -> ${plan.targetStage!.name}'}'
      '${plan.blockedBy.isEmpty ? '' : ', blockedBy=${plan.blockedBy.map((c) => c.name).join(",")}'}',
    );

    // VERIFY: re-check the plan against the checkpoint gate, independently.
    // This is the hard enforcement point: even a forged or buggy plan that
    // tries to advance past an unauthorized checkpoint is stopped here.
    plan = verifyPlan(plan, s);
    trace.add(
      'VERIFY: ${plan.checkpointViolated ? 'BLOCKED — checkpoint gate tripped' : 'plan is safe'}',
    );

    return plan.copyWith(phaseTrace: trace);
  }

  /// Find the first table row whose `from` matches the current stage and
  /// whose guard passes. Deterministic: table order is fixed.
  TransitionRule? _matchingRule(AgentSnapshot s) {
    for (final rule in transitionTable) {
      if (rule.from == s.task.stage && rule.guard(s)) {
        return rule;
      }
    }
    return null;
  }

  /// Checkpoints on [rule] that still lack an explicit user authorization.
  List<CheckpointKind> missingAuthorizations(
      TransitionRule rule, AgentSnapshot s) {
    return rule
        .checkpoints(s)
        .where((c) => !s.isAuthorized(c))
        .toList();
  }

  AgentPlan _propose(AgentSnapshot s, TransitionRule? rule) {
    if (s.task.stage == TaskStage.done) {
      return const AgentPlan(
        action: AgentAction.finished,
        rationale: 'Task is done; nothing left to plan.',
      );
    }
    if (rule == null) {
      return AgentPlan(
        action: AgentAction.waitForInput,
        rationale:
            'No transition is ready from stage "${s.task.stage.name}". '
            'Waiting for the user to provide what is missing.',
      );
    }
    final missing = missingAuthorizations(rule, s);
    if (missing.isNotEmpty) {
      return AgentPlan(
        action: AgentAction.requestAuthorization,
        targetStage: rule.to,
        blockedBy: missing,
        rationale:
            'Cannot move to "${rule.to.name}": waiting for the user to '
            'complete ${missing.map((c) => c.name).join(", ")}. '
            'The agent never passes a human checkpoint on its own.',
      );
    }
    return AgentPlan(
      action: AgentAction.advanceStage,
      targetStage: rule.to,
      rationale: rule.rationale,
    );
  }

  /// Independent second check of a proposed plan against the checkpoint gate.
  ///
  /// If [plan] tries to advance to a stage whose transition crosses a
  /// checkpoint without a recorded [UserAuthorization], the plan is
  /// downgraded to [AgentAction.requestAuthorization] and flagged via
  /// [AgentPlan.checkpointViolated]. Safe plans pass through unchanged.
  AgentPlan verifyPlan(AgentPlan plan, AgentSnapshot s) {
    if (plan.action != AgentAction.advanceStage || plan.targetStage == null) {
      return plan;
    }
    TransitionRule? rule;
    for (final r in transitionTable) {
      if (r.from == s.task.stage && r.to == plan.targetStage) {
        rule = r;
        break;
      }
    }
    if (rule == null) {
      // No such transition exists: this plan is invalid, stop it.
      return plan.copyWith(
        action: AgentAction.waitForInput,
        targetStage: null,
        checkpointViolated: true,
        rationale:
            'VERIFY rejected the plan: no legal transition from '
            '"${s.task.stage.name}" to "${plan.targetStage!.name}".',
      );
    }
    final missing = missingAuthorizations(rule, s);
    if (missing.isNotEmpty) {
      return plan.copyWith(
        action: AgentAction.requestAuthorization,
        blockedBy: missing,
        checkpointViolated: true,
        rationale:
            'VERIFY blocked the advance to "${rule.to.name}": missing user '
            'authorization for ${missing.map((c) => c.name).join(", ")}. '
            'Human checkpoints always require explicit recorded consent.',
      );
    }
    return plan;
  }
}
