// Agent engine structural tests: the OBSERVE -> UNDERSTAND -> REASON -> ACT ->
// VERIFY loop, the deterministic transition table, and planNext's
// action + rationale output.
//
// Checkpoint-specific blocking is covered in test/checkpoint_test.dart.
import 'package:ethio/agent/agent_engine.dart';
import 'package:ethio/models/task.dart';
import 'package:flutter_test/flutter_test.dart';

final _engine = AgentEngine();

ServiceTask _task({
  required TaskStage stage,
  Map<String, String> answers = const {},
  List<DocItem> docs = const [],
  List<ExtractedField> fields = const [],
  List<IssueItem> issues = const [],
}) {
  return ServiceTask(
    id: 't_engine',
    serviceId: 'passport',
    title: 'Engine test task',
    createdAt: DateTime.now(),
    stage: stage,
    answers: Map.of(answers),
    docs: List.of(docs),
    fields: List.of(fields),
    issues: List.of(issues),
    approvals: const [
      ApprovalKind.otp,
      ApprovalKind.payment,
      ApprovalKind.legal,
    ].map((k) => ApprovalItem(kind: k)).toList(),
  );
}

const _fullAnswers = {
  'purpose': 'Renewal',
  'full_name': 'Abebe Tesfaye',
  'dob': '1998-04-12',
  'phone': '+251911234567',
};

List<DocItem> _allDocs() => [
      'national_id',
      'photo',
      'old_passport',
      'birth_cert',
    ]
        .map((r) => DocItem(
              id: 'd_$r',
              requirementId: r,
              labelKey: r,
              fileName: '$r.pdf',
              fileType: 'PDF',
              sizeKb: 200,
            ))
        .toList();

void main() {
  group('planNext returns an action plus a rationale', () {
    test('requirements stage plans the move to documents', () {
      final plan = _engine.planNext(
        task: _task(stage: TaskStage.requirements),
        authorizations: const [],
      );
      expect(plan.action, AgentAction.advanceStage);
      expect(plan.targetStage, TaskStage.documents);
      expect(plan.rationale, isNotEmpty);
    });

    test('documents stage waits until every requirement has a document', () {
      final plan = _engine.planNext(
        task: _task(stage: TaskStage.documents, docs: [
          DocItem(
            id: 'd1',
            requirementId: 'national_id',
            labelKey: 'national_id',
            fileName: 'national_id.pdf',
            fileType: 'PDF',
            sizeKb: 200,
          ),
        ]),
        authorizations: const [],
      );
      expect(plan.action, AgentAction.waitForInput);
      expect(plan.targetStage, isNull);
      expect(plan.rationale, isNotEmpty);
    });

    test('documents stage advances once all documents are uploaded', () {
      final plan = _engine.planNext(
        task: _task(stage: TaskStage.documents, docs: _allDocs()),
        authorizations: const [],
      );
      expect(plan.action, AgentAction.advanceStage);
      expect(plan.targetStage, TaskStage.review);
    });

    test('issues stage waits while an issue is open', () {
      final plan = _engine.planNext(
        task: _task(
          stage: TaskStage.issues,
          docs: _allDocs(),
          fields: [
            ExtractedField(
                id: 'f1', labelKey: 'x', value: 'y', confidence: 0.9),
          ],
          issues: [
            IssueItem(
                id: 'i1', kind: 'missing', title: 't', detail: 'd'),
          ],
        ),
        authorizations: const [],
      );
      expect(plan.action, AgentAction.waitForInput);
    });

    test('done stage plans nothing', () {
      final plan = _engine.planNext(
        task: _task(stage: TaskStage.done),
        authorizations: const [],
      );
      expect(plan.action, AgentAction.finished);
    });
  });

  group('deterministic transition table', () {
    test('same snapshot always yields the same plan', () {
      final task = _task(stage: TaskStage.requirements, answers: _fullAnswers);
      final a = _engine.planNext(task: task, authorizations: const []);
      final b = _engine.planNext(task: task, authorizations: const []);
      expect(a.action, b.action);
      expect(a.targetStage, b.targetStage);
      expect(a.rationale, b.rationale);
      expect(a.blockedBy, b.blockedBy);
    });

    test('every non-terminal stage has a table row', () {
      final fromStages =
          transitionTable.map((r) => r.from).toSet();
      for (final stage in TaskStage.values) {
        if (stage == TaskStage.done) continue;
        expect(fromStages, contains(stage),
            reason: 'no transition row starts at $stage');
      }
    });

    test('table is generic: no service id appears in any rule', () {
      for (final rule in transitionTable) {
        expect(rule.rationale, isNot(contains('passport')));
        expect(rule.rationale, isNot(contains('visa')));
      }
    });
  });

  group('full cycle trace', () {
    test('runCycle walks all five phases in order', () {
      final snapshot = AgentSnapshot.fromTask(
        _task(stage: TaskStage.requirements),
        const [],
      );
      final plan = _engine.runCycle(snapshot);
      expect(plan.phaseTrace, hasLength(5));
      expect(plan.phaseTrace[0], startsWith('OBSERVE:'));
      expect(plan.phaseTrace[1], startsWith('UNDERSTAND:'));
      expect(plan.phaseTrace[2], startsWith('REASON:'));
      expect(plan.phaseTrace[3], startsWith('ACT:'));
      expect(plan.phaseTrace[4], startsWith('VERIFY:'));
    });

    test('engine never mutates the task', () {
      final task = _task(stage: TaskStage.requirements);
      _engine.planNext(task: task, authorizations: const []);
      expect(task.stage, TaskStage.requirements);
      expect(task.docs, isEmpty);
      expect(task.fields, isEmpty);
    });
  });
}
