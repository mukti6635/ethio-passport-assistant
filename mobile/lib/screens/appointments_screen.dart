import 'package:flutter/material.dart';

import '../l10n/strings.dart';
import '../state/task_store.dart';
import '../theme/ethio_theme.dart';
import '../widgets/core.dart';

/// Appointment selection: office, day, time slot → confirmation card.
/// References are demo-only and labeled as such.
class AppointmentsScreen extends StatefulWidget {
  const AppointmentsScreen({super.key, required this.taskId});

  final String taskId;

  @override
  State<AppointmentsScreen> createState() => _AppointmentsScreenState();
}

class _AppointmentsScreenState extends State<AppointmentsScreen> {
  static const _offices = [
    'Addis Ababa — Main Office',
    'Adama Branch',
    'Hawassa Branch',
  ];
  static const _slots = [
    '9:00 AM',
    '10:30 AM',
    '12:00 PM',
    '2:00 PM',
    '3:30 PM',
  ];
  static const _weekdays = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  static const _months = [
    'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'
  ];

  int _office = 0;
  int _day = 1;
  int _slot = 1;

  List<DateTime> get _days => List.generate(
      14, (i) => DateTime.now().add(Duration(days: i + 1)));

  String _dayLabel(DateTime d) =>
      '${_weekdays[d.weekday - 1]}, ${_months[d.month - 1]} ${d.day}';

  @override
  Widget build(BuildContext context) {
    final s = S.of(context);
    final task = TaskStore.instance.taskById(widget.taskId)!;
    final confirmed = task.appointment != null;
    return ScreenScaffold(
      title: s.t('apt_title'),
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (!confirmed) ...[
            Text(s.t('apt_office'), style: EthioText.h3),
            const SizedBox(height: 10),
            for (var i = 0; i < _offices.length; i++)
              Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: InkWell(
                  onTap: () => setState(() => _office = i),
                  borderRadius: BorderRadius.circular(14),
                  child: Container(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 18, vertical: 16),
                    decoration: BoxDecoration(
                      color: _office == i
                          ? EthioColors.primarySoft
                          : Colors.white,
                      borderRadius: BorderRadius.circular(14),
                      border: Border.all(
                        color: _office == i
                            ? EthioColors.primary
                            : EthioColors.line,
                        width: _office == i ? 2 : 1,
                      ),
                    ),
                    child: Row(
                      children: [
                        const Icon(Icons.location_on_outlined,
                            color: EthioColors.primary),
                        const SizedBox(width: 12),
                        Expanded(
                          child: Text(_offices[i],
                              style: const TextStyle(
                                  fontSize: 16,
                                  fontWeight: FontWeight.w600)),
                        ),
                        if (_office == i)
                          const Icon(Icons.check_circle,
                              color: EthioColors.primary),
                      ],
                    ),
                  ),
                ),
              ),
            const SizedBox(height: 12),
            Text(s.t('apt_day'), style: EthioText.h3),
            const SizedBox(height: 10),
            SizedBox(
              height: 78,
              child: ListView.separated(
                scrollDirection: Axis.horizontal,
                itemCount: _days.length,
                separatorBuilder: (_, __) =>
                    const SizedBox(width: 10),
                itemBuilder: (context, i) {
                  final d = _days[i];
                  final selected = _day == i;
                  return InkWell(
                    onTap: () => setState(() => _day = i),
                    borderRadius: BorderRadius.circular(14),
                    child: Container(
                      width: 68,
                      decoration: BoxDecoration(
                        color: selected
                            ? EthioColors.primary
                            : Colors.white,
                        borderRadius: BorderRadius.circular(14),
                        border: Border.all(
                            color: selected
                                ? EthioColors.primary
                                : EthioColors.line),
                      ),
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Text(_weekdays[d.weekday - 1],
                              style: TextStyle(
                                  fontSize: 13,
                                  fontWeight: FontWeight.w700,
                                  color: selected
                                      ? Colors.white
                                      : EthioColors.muted)),
                          const SizedBox(height: 2),
                          Text('${d.day}',
                              style: TextStyle(
                                  fontSize: 20,
                                  fontWeight: FontWeight.w800,
                                  color: selected
                                      ? Colors.white
                                      : EthioColors.ink)),
                        ],
                      ),
                    ),
                  );
                },
              ),
            ),
            const SizedBox(height: 16),
            Text(s.t('apt_time'), style: EthioText.h3),
            const SizedBox(height: 10),
            Wrap(
              spacing: 10,
              runSpacing: 10,
              children: [
                for (var i = 0; i < _slots.length; i++)
                  InkWell(
                    onTap: () => setState(() => _slot = i),
                    borderRadius: BorderRadius.circular(999),
                    child: Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 20, vertical: 14),
                      decoration: BoxDecoration(
                        color: _slot == i
                            ? EthioColors.primary
                            : Colors.white,
                        borderRadius: BorderRadius.circular(999),
                        border: Border.all(
                            color: _slot == i
                                ? EthioColors.primary
                                : EthioColors.line,
                            width: 1.6),
                      ),
                      child: Text(_slots[i],
                          style: TextStyle(
                              fontSize: 15,
                              fontWeight: FontWeight.w700,
                              color: _slot == i
                                  ? Colors.white
                                  : EthioColors.ink)),
                    ),
                  ),
              ],
            ),
            const SizedBox(height: 24),
            EthioButton(
              label: s.t('apt_confirm'),
              icon: Icons.event_available_outlined,
              onPressed: () {
                TaskStore.instance.bookAppointment(
                  task,
                  _offices[_office],
                  _dayLabel(_days[_day]),
                  _slots[_slot],
                );
                setState(() {});
              },
            ),
          ] else ...[
            const SizedBox(height: 16),
            Container(
              padding: const EdgeInsets.all(24),
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.circular(20),
                border: Border.all(color: EthioColors.ok, width: 1.6),
              ),
              child: Column(
                children: [
                  const Icon(Icons.check_circle,
                      size: 72, color: EthioColors.ok),
                  const SizedBox(height: 12),
                  Text(s.t('apt_confirmed'), style: EthioText.h2),
                  const SizedBox(height: 16),
                  _row(s.t('apt_summary'), task.title),
                  _row(s.t('apt_office'),
                      task.appointment!.office),
                  _row('Date', task.appointment!.dayLabel),
                  _row('Time', task.appointment!.timeLabel),
                  const SizedBox(height: 12),
                  Container(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 18, vertical: 12),
                    decoration: BoxDecoration(
                      color: EthioColors.bg,
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: Text(
                      '${s.t('apt_ref')}: ${task.appointment!.reference}',
                      style: const TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.w800,
                          letterSpacing: 1),
                    ),
                  ),
                  const SizedBox(height: 8),
                  Text(s.t('apt_ref_note'),
                      textAlign: TextAlign.center,
                      style: EthioText.caption),
                ],
              ),
            ),
            const SizedBox(height: 20),
            EthioButton(
              label: s.t('common_done'),
              onPressed: () => Navigator.of(context)
                  .pushNamedAndRemoveUntil('/', (r) => false),
            ),
          ],
        ],
      ),
    );
  }

  Widget _row(String label, String value) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(width: 110, child: Text(label, style: EthioText.small)),
          Expanded(child: Text(value, style: EthioText.smallBold)),
        ],
      ),
    );
  }
}
