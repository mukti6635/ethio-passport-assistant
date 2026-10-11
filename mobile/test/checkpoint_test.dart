// Checkpoint enforcement tests: the agent must NEVER advance past a human
// checkpoint (OTP / CAPTCHA / payment / legal / appointment booking) without
// an explicit recorded [UserAuthorization].
//
// One test per checkpoint kind. Each test builds a task that is otherwise
// fully ready to advance, withholds the authorization for that one
// checkpoint, and asserts the engine blocks — then grants it and asserts
// the engine lets the task through.
import 'package:ethio/agent/agent_engine.dart';
import 'package:ethio/models/task.dart';
import 'package:flutter_test/flutter_test.dart';

final _engine = AgentEngine();

// A task sitting at [stage] whose approvals are all marked approved, so the
// ONLY thing that can block it is a missing checkpoint authorization.
ServiceTask _readyTask({
  required String serviceId,
  required TaskStage stage,
}) {
  return ServiceTask(
    id: 't_checkpoint',
    serviceId: serviceId,
    title: 'Checkpoint test task',
    createdAt: DateTime.now(),
    stage: stage,
    answers: const {
      'purpose': 'Renewal',
      'full_name': 'Abebe Tesfaye',
      'dob': '1998-04-12',
      'phone': '+251911234567',
      'license_class': 'Class B (car)',
    },
    approvals: const [
      ApprovalKind.otp,
      ApprovalKind.captcha,
      ApprovalKind.payment,
      ApprovalKind.legal,
    ].map((k) => ApprovalItem(kind: k, status: ApprovalStatus.approved)).toList(),
  );
}

List<UserAuthorization> _auths(List<CheckpointKind> kinds) =>
    kinds.map((k) => UserAuthorization(checkpoint: k)).toList();

void main() {
  group('checkpoint enforcement (approvals -> appointment)', () {
    // 'license' needs otp + captcha + payment + legal.
    test('refuses to advance past OTP without authorization', () {
      final task = _readyTask(serviceId: 'license', stage: TaskStage.approvals);
      final plan = _engine.planNext(
        task: task,
        authorizations: _auths([
          CheckpointKind.captcha,
          CheckpointKind.payment,
          CheckpointKind.legal,
        ]),
      );
      expect(plan.action, AgentAction.requestAuthorization);
      expect(plan.blockedBy, contains(CheckpointKind.otp));
    });

    test('refuses to advance past CAPTCHA without authorization', () {
      final task = _readyTask(serviceId: 'license', stage: TaskStage.approvals);
      final plan = _engine.planNext(
        task: task,
        authorizations: _auths([
          CheckpointKind.otp,
          CheckpointKind.payment,
          CheckpointKind.legal,
        ]),
      );
      expect(plan.action, AgentAction.requestAuthorization);
      expect(plan.blockedBy, contains(CheckpointKind.captcha));
    });

    test('refuses to advance past payment without authorization', () {
      final task = _readyTask(serviceId: 'license', stage: TaskStage.approvals);
      final plan = _engine.planNext(
        task: task,
        authorizations: _auths([
          CheckpointKind.otp,
          CheckpointKind.captcha,
          CheckpointKind.legal,
        ]),
      );
      expect(plan.action, AgentAction.requestAuthorization);
      expect(plan.blockedBy, contains(CheckpointKind.payment));
    });

    test('refuses to advance past legal review without authorization', () {
      // 'passport' needs otp + payment + legal.
      final task = _readyTask(serviceId: 'passport', stage: TaskStage.approvals);
      final plan = _engine.planNext(
        task: task,
        authorizations: _auths([
          CheckpointKind.otp,
          CheckpointKind.payment,
        ]),
      );
      expect(plan.action, AgentAction.requestAuthorization);
      expect(plan.blockedBy, contains(CheckpointKind.legal));
    });

    test('advances when every checkpoint is authorized', () {
      final task = _readyTask(serviceId: 'passport', stage: TaskStage.approvals);
      final plan = _engine.planNext(
        task: task,
        authorizations: _auths([
          CheckpointKind.otp,
          CheckpointKind.payment,
          CheckpointKind.legal,
        ]),
      );
      expect(plan.action, AgentAction.advanceStage);
      expect(plan.targetStage, TaskStage.appointment);
      expect(plan.blockedBy, isEmpty);
      expect(plan.checkpointViolated, isFalse);
    });
  });

  group('checkpoint enforcement (appointment -> done)', () {
    ServiceTask bookedTask() {
      final task =
          _readyTask(serviceId: 'passport', stage: TaskStage.appointment);
      task.appointment = AppointmentInfo(
        office: 'Addis Ababa — Main Office',
        dayLabel: 'Mon, Oct 12',
        timeLabel: '10:30 AM',
        reference: 'TEST-0001',
      );
      return task;
    }

    test('refuses to finish without appointment-booking authorization', () {
      final plan = _engine.planNext(
        task: bookedTask(),
        authorizations: const [],
      );
      expect(plan.action, AgentAction.requestAuthorization);
      expect(plan.blockedBy, contains(CheckpointKind.appointmentBooking));
    });

    test('finishes once the user authorizes the appointment booking', () {
      final plan = _engine.planNext(
        task: bookedTask(),
        authorizations: _auths([CheckpointKind.appointmentBooking]),
      );
      expect(plan.action, AgentAction.advanceStage);
      expect(plan.targetStage, TaskStage.done);
      expect(plan.checkpointViolated, isFalse);
    });
  });

  group('verify is a second, independent enforcement point', () {
    test('verifyPlan stops a forged plan that skips authorization', () {
      final task = _readyTask(serviceId: 'passport', stage: TaskStage.approvals);
      final snapshot = AgentSnapshot.fromTask(task, const []);
      // A forged plan: advance with no authorizations at all.
      const forged = AgentPlan(
        action: AgentAction.advanceStage,
        targetStage: TaskStage.appointment,
        rationale: 'forged',
      );
      final checked = _engine.verifyPlan(forged, snapshot);
      expect(checked.action, AgentAction.requestAuthorization);
      expect(checked.checkpointViolated, isTrue);
      expect(
        checked.blockedBy,
        containsAll([
          CheckpointKind.otp,
          CheckpointKind.payment,
          CheckpointKind.legal,
        ]),
      );
    });

    test('verifyPlan rejects a transition that does not exist', () {
      final task =
          _readyTask(serviceId: 'passport', stage: TaskStage.requirements);
      final snapshot = AgentSnapshot.fromTask(task, const []);
      const forged = AgentPlan(
        action: AgentAction.advanceStage,
        targetStage: TaskStage.done, // no such jump in the table
        rationale: 'forged',
      );
      final checked = _engine.verifyPlan(forged, snapshot);
      expect(checked.action, isNot(AgentAction.advanceStage));
      expect(checked.checkpointViolated, isTrue);
    });
  });
}
