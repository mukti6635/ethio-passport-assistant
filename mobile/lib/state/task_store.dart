import 'package:flutter/foundation.dart';

import '../data/service_catalog.dart';
import '../models/task.dart';

/// In-memory store for the prototype. All state lives here so every screen
/// renders from a single source of truth. Nothing is persisted and no real
/// personal data is stored — sample values are clearly placeholders.
class TaskStore extends ChangeNotifier {
  TaskStore._() {
    _seedDemoData();
  }

  static final TaskStore instance = TaskStore._();

  final List<ServiceTask> _tasks = [];
  int _seq = 0;

  List<ServiceTask> get tasks => List.unmodifiable(_tasks);

  List<ServiceTask> get activeTasks =>
      _tasks.where((t) => !t.isDone).toList();

  List<ServiceTask> get doneTasks => _tasks.where((t) => t.isDone).toList();

  ServiceTask? taskById(String id) {
    for (final t in _tasks) {
      if (t.id == id) return t;
    }
    return null;
  }

  String _nextId() => 'task_${++_seq}_${DateTime.now().millisecondsSinceEpoch}';

  /// Create a task from the generic intake answers and drop it at the
  /// requirements stage.
  ServiceTask createTask(String serviceId, Map<String, String> answers,
      {String? titleOverride}) {
    final def = serviceById(serviceId);
    final task = ServiceTask(
      id: _nextId(),
      serviceId: serviceId,
      title: titleOverride ?? _titleFor(def.id, answers),
      createdAt: DateTime.now(),
      stage: TaskStage.requirements,
      answers: Map.of(answers),
      approvals: def.approvals.map((k) => ApprovalItem(kind: k)).toList(),
      aiSteps: def.aiStepKeys.map((k) => AiStep(labelKey: k)).toList(),
    );
    _tasks.insert(0, task);
    notifyListeners();
    return task;
  }

  static String _titleFor(String serviceId, Map<String, String> answers) {
    final base = {
      'passport': 'Passport application',
      'visa': 'Visa application',
      'license': "Driver's license",
      'certificates': 'Certificate request',
      'business': 'Business license',
      'other': 'Service request',
    }[serviceId]!;
    final purpose = answers['purpose'];
    return purpose == null || purpose.isEmpty ? base : '$base — $purpose';
  }

  // ---------------------------------------------------------------- documents

  void addSampleDoc(ServiceTask task, String requirementId) {
    final def = serviceById(task.serviceId);
    final req = def.requirements.firstWhere((r) => r.id == requirementId);
    final n = task.docs.where((d) => d.requirementId == requirementId).length + 1;
    final type = req.acceptedTypes.first;
    task.docs.add(DocItem(
      id: 'doc_${task.docs.length}_${DateTime.now().millisecondsSinceEpoch}',
      requirementId: requirementId,
      labelKey: req.labelKey,
      fileName:
          '${req.id}_$n.${type.toLowerCase()}',
      fileType: type,
      sizeKb: 180 + (n * 37) % 900,
    ));
    notifyListeners();
  }

  void removeDoc(ServiceTask task, String docId) {
    task.docs.removeWhere((d) => d.id == docId);
    notifyListeners();
  }

  /// Simulate the AI reading the documents. Produces placeholder fields —
  /// clearly fake values, never real data.
  void runExtraction(ServiceTask task) {
    if (task.fields.isNotEmpty) return;
    final name = task.answers['full_name'];
    task.fields.addAll([
      ExtractedField(
          id: 'f_name',
          labelKey: 'Full name',
          value: (name == null || name.isEmpty) ? 'Abebe Tesfaye' : name,
          confidence: 0.97),
      ExtractedField(
          id: 'f_dob',
          labelKey: 'Date of birth',
          value: task.answers['dob'] ?? '1998-04-12',
          confidence: 0.93),
      ExtractedField(
          id: 'f_id',
          labelKey: 'ID number',
          value: 'ET-••••-4821',
          confidence: 0.88),
      ExtractedField(
          id: 'f_phone',
          labelKey: 'Phone',
          value: task.answers['phone'] ?? '+251 9• ••• •••',
          confidence: 0.81),
    ]);
    // Seed one missing item and one conflict so the issues screen has content.
    task.issues.addAll([
      IssueItem(
        id: 'iss_phone',
        kind: 'missing',
        title: 'Phone number is missing',
        detail:
            'The documents do not show a phone number. ETHIO needs one to contact you.',
      ),
      IssueItem(
        id: 'iss_name',
        kind: 'conflict',
        title: 'Name spelling differs',
        detail: 'Your ID and your photo form spell the name differently.',
        options: ['Abebe Tesfaye', 'Abebe Tesfay'],
      ),
    ]);
    notifyListeners();
  }

  void updateField(ServiceTask task, String fieldId, String value) {
    final f = task.fields.firstWhere((e) => e.id == fieldId);
    f.value = value;
    f.edited = true;
    notifyListeners();
  }

  void resolveIssue(ServiceTask task, String issueId, String resolution) {
    final i = task.issues.firstWhere((e) => e.id == issueId);
    i.resolution = resolution;
    notifyListeners();
  }

  // --------------------------------------------------------------- progression

  void advanceStage(ServiceTask task, TaskStage stage) {
    task.stage = stage;
    // Reset AI steps when entering the AI stage so the simulation replays.
    if (stage == TaskStage.approvals) {
      for (final s in task.aiSteps) {
        s.status = AiStepStatus.waiting;
        s.finishedAt = null;
      }
    }
    notifyListeners();
  }

  /// Move the simulated AI worker one step forward. Returns false when the
  /// whole sequence is finished.
  bool advanceAiStep(ServiceTask task) {
    for (final s in task.aiSteps) {
      if (s.status == AiStepStatus.waiting) {
        s.status = AiStepStatus.running;
        notifyListeners();
        return true;
      }
      if (s.status == AiStepStatus.running) {
        s.status = AiStepStatus.done;
        s.finishedAt = DateTime.now();
        notifyListeners();
        // Immediately start the next one so the timeline feels continuous.
        final next = task.aiSteps
            .where((x) => x.status == AiStepStatus.waiting)
            .firstOrNull;
        if (next != null) {
          next.status = AiStepStatus.running;
          notifyListeners();
          return true;
        }
        return false;
      }
    }
    return false;
  }

  void approve(ServiceTask task, ApprovalKind kind) {
    final a = task.approvals.firstWhere((e) => e.kind == kind);
    a.status = ApprovalStatus.approved;
    notifyListeners();
  }

  void bookAppointment(
      ServiceTask task, String office, String dayLabel, String timeLabel) {
    task.appointment = AppointmentInfo(
      office: office,
      dayLabel: dayLabel,
      timeLabel: timeLabel,
      reference:
          'DEMO-${(DateTime.now().millisecondsSinceEpoch % 900000 + 100000)}',
    );
    task.stage = TaskStage.done;
    notifyListeners();
  }

  void finishWithoutAppointment(ServiceTask task) {
    task.stage = TaskStage.done;
    notifyListeners();
  }

  // ------------------------------------------------------------------ demo seed

  void _seedDemoData() {
    // One active task mid-flow so every screen is explorable immediately.
    final active = ServiceTask(
      id: 'task_demo_active',
      serviceId: 'passport',
      title: 'Passport application — Renewal',
      createdAt: DateTime.now().subtract(const Duration(days: 1)),
      stage: TaskStage.requirements,
      answers: {'purpose': 'Renewal', 'phone': '+251 911 234 567'},
      approvals: const [
        ApprovalKind.otp,
        ApprovalKind.payment,
        ApprovalKind.legal
      ].map((k) => ApprovalItem(kind: k)).toList(),
      aiSteps: const [
        'Checking the requirements',
        'Verifying your documents',
        'Drafting your application',
        'Preparing everything for review',
      ].map((k) => AiStep(labelKey: k)).toList(),
    );
    _tasks.add(active);

    // One finished task for the history screen.
    final done = ServiceTask(
      id: 'task_demo_done',
      serviceId: 'certificates',
      title: 'Certificate request — Birth certificate',
      createdAt: DateTime.now().subtract(const Duration(days: 9)),
      stage: TaskStage.done,
      answers: {'cert_type': 'Birth certificate'},
      approvals: const [
        ApprovalKind.otp,
        ApprovalKind.payment,
        ApprovalKind.legal
      ].map((k) => ApprovalItem(kind: k, status: ApprovalStatus.approved)).toList(),
      aiSteps: const [
        'Checking the requirements',
        'Verifying your documents',
        'Drafting your application',
        'Preparing everything for review',
      ]
          .map((k) => AiStep(labelKey: k, status: AiStepStatus.done))
          .toList(),
    );
    done.appointment = AppointmentInfo(
      office: 'Addis Ababa — Main Office',
      dayLabel: 'Mon, Oct 5',
      timeLabel: '10:30 AM',
      reference: 'DEMO-482103',
    );
    _tasks.add(done);
    _seq = 2;
  }
}
