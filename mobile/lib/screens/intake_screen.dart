import 'package:flutter/material.dart';

import '../data/service_catalog.dart';
import '../l10n/strings.dart';
import '../models/service.dart';
import '../state/task_store.dart';
import '../theme/ethio_theme.dart';
import '../widgets/core.dart';

/// Generic service intake: renders one question per screen from the
/// [ServiceDefinition]. No service-specific UI lives here — new services only
/// add data to the catalog.
class IntakeScreen extends StatefulWidget {
  const IntakeScreen({super.key, required this.serviceId});

  final String serviceId;

  @override
  State<IntakeScreen> createState() => _IntakeScreenState();
}

class _IntakeScreenState extends State<IntakeScreen> {
  final _pageController = PageController();
  final Map<String, String> _answers = {};
  int _page = 0;
  String? _choice;

  @override
  void dispose() {
    _pageController.dispose();
    super.dispose();
  }

  ServiceDefinition get _def => serviceById(widget.serviceId);

  int get _total => _def.questions.length;

  IntakeQuestion get _q => _def.questions[_page];

  bool get _canContinue {
    switch (_q.type) {
      case QuestionType.choice:
        return (_choice ?? '').isNotEmpty;
      case QuestionType.text:
      case QuestionType.phone:
      case QuestionType.date:
        return (_answers[_q.id] ?? '').trim().isNotEmpty;
    }
  }

  void _saveCurrent() {
    if (_q.type == QuestionType.choice && _choice != null) {
      // _choice holds the option key; store the display string so
      // downstream screens (review, legal) keep working unchanged.
      _answers[_q.id] = S.of(context).t(_choice!);
    }
  }

  void _next() {
    _saveCurrent();
    if (_page < _total - 1) {
      setState(() {
        _choice = null;
        _page++;
      });
      _pageController.nextPage(
          duration: const Duration(milliseconds: 280),
          curve: Curves.easeOut);
    } else {
      _finish();
    }
  }

  void _back() {
    if (_page > 0) {
      setState(() {
        _choice = null;
        _page--;
      });
      _pageController.previousPage(
          duration: const Duration(milliseconds: 280),
          curve: Curves.easeOut);
    } else {
      Navigator.of(context).pop();
    }
  }

  void _finish() {
    final task = TaskStore.instance.createTask(widget.serviceId, _answers);
    Navigator.of(context).pushReplacementNamed('/task', arguments: task.id);
  }

  @override
  Widget build(BuildContext context) {
    final s = S.of(context);
    return ScreenScaffold(
      title: s.t(_def.titleKey),
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(s.t('intake_title'), style: EthioText.h2),
          const SizedBox(height: 6),
          Text(s.t('intake_step',
              {'n': '${_page + 1}', 'total': '$_total'}),
              style: EthioText.bodyMuted),
          const SizedBox(height: 8),
          ClipRRect(
            borderRadius: BorderRadius.circular(999),
            child: LinearProgressIndicator(
              value: (_page + 1) / _total,
              minHeight: 8,
              backgroundColor: EthioColors.primary12,
              valueColor:
                  const AlwaysStoppedAnimation<Color>(EthioColors.primary),
            ),
          ),
          const SizedBox(height: 16),
          Expanded(
            child: PageView.builder(
              controller: _pageController,
              physics: const NeverScrollableScrollPhysics(),
              itemCount: _total,
              itemBuilder: (context, i) =>
                  _QuestionPage(def: _def, question: _def.questions[i], state: this),
            ),
          ),
          const SizedBox(height: 12),
          EthioButton(
            label: _page == _total - 1
                ? s.t('intake_finish')
                : s.t('intake_continue'),
            icon: Icons.arrow_forward,
            onPressed: _canContinue ? _next : null,
          ),
          const SizedBox(height: 8),
          TextButton(
            onPressed: _back,
            child: Text(s.t('intake_back')),
          ),
        ],
      ),
      scrollable: false,
    );
  }
}

class _QuestionPage extends StatefulWidget {
  const _QuestionPage(
      {required this.def, required this.question, required this.state});

  final ServiceDefinition def;
  final IntakeQuestion question;
  final _IntakeScreenState state;

  @override
  State<_QuestionPage> createState() => _QuestionPageState();
}

class _QuestionPageState extends State<_QuestionPage> {
  late final TextEditingController _controller;

  @override
  void initState() {
    super.initState();
    _controller = TextEditingController(
        text: widget.state._answers[widget.question.id] ?? '');
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final q = widget.question;
    final label =
        catalogLabel(S.of(context), widget.def.id, 'question', q.id);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(label, style: EthioText.h3),
        const SizedBox(height: 16),
        Expanded(child: _fieldFor(q)),
      ],
    );
  }

  Widget _fieldFor(IntakeQuestion q) {
    switch (q.type) {
      case QuestionType.choice:
        return ListView.separated(
          itemCount: q.options.length,
          separatorBuilder: (_, __) => const SizedBox(height: 10),
          itemBuilder: (context, i) {
            final opt = q.options[i];
            final label = S.of(context).t(opt);
            final selected = widget.state._choice == opt;
            return InkWell(
              onTap: () => setState(() {
                widget.state._choice = opt;
                widget.state.setState(() {});
              }),
              borderRadius: BorderRadius.circular(16),
              child: Container(
                padding: const EdgeInsets.symmetric(
                    horizontal: 18, vertical: 18),
                decoration: BoxDecoration(
                  color: selected
                      ? EthioColors.primarySoft
                      : Colors.white,
                  borderRadius: BorderRadius.circular(16),
                  border: Border.all(
                    color: selected
                        ? EthioColors.primary
                        : EthioColors.line,
                    width: selected ? 2 : 1,
                  ),
                ),
                child: Row(
                  children: [
                    Expanded(
                      child: Text(label,
                          style: TextStyle(
                              fontSize: 17,
                              fontWeight: selected
                                  ? FontWeight.w800
                                  : FontWeight.w600,
                              color: selected
                                  ? EthioColors.primaryDark
                                  : EthioColors.ink)),
                    ),
                    if (selected)
                      const Icon(Icons.check_circle,
                          color: EthioColors.primary),
                  ],
                ),
              ),
            );
          },
        );
      case QuestionType.text:
      case QuestionType.phone:
        return TextField(
          controller: _controller,
          keyboardType: q.type == QuestionType.phone
              ? TextInputType.phone
              : TextInputType.text,
          style: const TextStyle(fontSize: 18),
          decoration: const InputDecoration(),
          onChanged: (v) {
            widget.state._answers[q.id] = v;
            widget.state.setState(() {});
          },
        );
      case QuestionType.date:
        return _DateField(
          initial: widget.state._answers[q.id],
          onPicked: (v) {
            widget.state._answers[q.id] = v;
            widget.state.setState(() {});
            setState(() {});
          },
        );
    }
  }
}

class _DateField extends StatelessWidget {
  const _DateField({required this.initial, required this.onPicked});

  final String? initial;
  final ValueChanged<String> onPicked;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: () async {
        final now = DateTime.now();
        final picked = await showDatePicker(
          context: context,
          initialDate: DateTime(now.year - 25),
          firstDate: DateTime(1920),
          lastDate: now,
        );
        if (picked != null) {
          onPicked(
              '${picked.year}-${picked.month.toString().padLeft(2, '0')}-${picked.day.toString().padLeft(2, '0')}');
        }
      },
      borderRadius: BorderRadius.circular(14),
      child: Container(
        padding:
            const EdgeInsets.symmetric(horizontal: 18, vertical: 18),
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(14),
          border: Border.all(color: EthioColors.line),
        ),
        child: Row(
          children: [
            const Icon(Icons.calendar_month_outlined,
                color: EthioColors.primary),
            const SizedBox(width: 12),
            Text(
              initial ?? 'YYYY-MM-DD',
              style: TextStyle(
                  fontSize: 18,
                  color: initial == null
                      ? EthioColors.muted
                      : EthioColors.ink,
                  fontWeight: initial == null
                      ? FontWeight.w400
                      : FontWeight.w700),
            ),
          ],
        ),
      ),
    );
  }
}
