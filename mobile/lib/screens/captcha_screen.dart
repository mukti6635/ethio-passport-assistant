import 'dart:math';

import 'package:flutter/material.dart';

import '../l10n/strings.dart';
import '../models/task.dart';
import '../state/task_store.dart';
import '../theme/ethio_theme.dart';
import '../widgets/core.dart';

/// Human approval: tap-based CAPTCHA mock. The user first ticks
/// "I'm not a robot", then picks the target tiles.
class CaptchaScreen extends StatefulWidget {
  const CaptchaScreen({super.key, required this.taskId});

  final String taskId;

  @override
  State<CaptchaScreen> createState() => _CaptchaScreenState();
}

class _CaptchaScreenState extends State<CaptchaScreen> {
  bool _human = false;
  late final List<_Tile> _tiles;
  String? _error;

  static const _targetIcon = Icons.pedal_bike_outlined;
  static const _pool = [
    Icons.directions_car_outlined,
    Icons.pedal_bike_outlined,
    Icons.flight_outlined,
    Icons.directions_bus_outlined,
    Icons.sailing_outlined,
    Icons.train_outlined,
  ];

  @override
  void initState() {
    super.initState();
    final rand = Random(42);
    final icons = <IconData>[];
    // 3 targets + 6 distractors, shuffled.
    icons.addAll(List.filled(3, _targetIcon));
    while (icons.length < 9) {
      final candidate = _pool[rand.nextInt(_pool.length)];
      if (candidate != _targetIcon) icons.add(candidate);
    }
    icons.shuffle(rand);
    _tiles = icons.map((i) => _Tile(icon: i, selected: false)).toList();
  }

  void _verify() {
    final s = S.of(context);
    final ok = _tiles.every((t) =>
        (t.icon == _targetIcon && t.selected) ||
        (t.icon != _targetIcon && !t.selected));
    if (!ok) {
      setState(() => _error =
          s.t('captcha_error', {'target': s.t('captcha_target')}));
      return;
    }
    final task = TaskStore.instance.taskById(widget.taskId)!;
    TaskStore.instance.approve(task, ApprovalKind.captcha);
    Navigator.of(context).pop();
  }

  @override
  Widget build(BuildContext context) {
    final s = S.of(context);
    return ScreenScaffold(
      title: s.t('captcha_title'),
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (!_human) ...[
            const SizedBox(height: 24),
            InkWell(
              onTap: () => setState(() => _human = true),
              borderRadius: BorderRadius.circular(16),
              child: Container(
                padding: const EdgeInsets.all(20),
                decoration: BoxDecoration(
                  color: Colors.white,
                  borderRadius: BorderRadius.circular(16),
                  border: Border.all(color: EthioColors.line),
                ),
                child: Row(
                  children: [
                    Container(
                      width: 34,
                      height: 34,
                      decoration: BoxDecoration(
                        borderRadius: BorderRadius.circular(8),
                        border: Border.all(
                            color: EthioColors.muted, width: 2),
                      ),
                    ),
                    const SizedBox(width: 16),
                    Text(s.t('captcha_robot'),
                        style: const TextStyle(
                            fontSize: 18,
                            fontWeight: FontWeight.w600)),
                  ],
                ),
              ),
            ),
          ] else ...[
            Text(
              s.t('captcha_body',
                  {'target': s.t('captcha_target')}),
              style: EthioText.h3,
            ),
            const SizedBox(height: 16),
            GridView.builder(
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              gridDelegate:
                  const SliverGridDelegateWithFixedCrossAxisCount(
                crossAxisCount: 3,
                mainAxisSpacing: 10,
                crossAxisSpacing: 10,
              ),
              itemCount: _tiles.length,
              itemBuilder: (context, i) {
                final tile = _tiles[i];
                return InkWell(
                  onTap: () => setState(
                      () => tile.selected = !tile.selected),
                  borderRadius: BorderRadius.circular(14),
                  child: Container(
                    decoration: BoxDecoration(
                      color: tile.selected
                          ? EthioColors.primarySoft
                          : Colors.white,
                      borderRadius: BorderRadius.circular(14),
                      border: Border.all(
                        color: tile.selected
                            ? EthioColors.primary
                            : EthioColors.line,
                        width: tile.selected ? 3 : 1,
                      ),
                    ),
                    child: Icon(tile.icon,
                        size: 44,
                        color: tile.selected
                            ? EthioColors.primaryDark
                            : EthioColors.muted),
                  ),
                );
              },
            ),
            if (_error != null) ...[
              const SizedBox(height: 12),
              Text(_error!,
                  textAlign: TextAlign.center,
                  style: const TextStyle(
                      color: EthioColors.danger,
                      fontWeight: FontWeight.w600)),
            ],
            const SizedBox(height: 20),
            EthioButton(
              label: s.t('captcha_verify'),
              icon: Icons.shield_outlined,
              onPressed: _verify,
            ),
          ],
        ],
      ),
    );
  }
}

class _Tile {
  _Tile({required this.icon, required this.selected});

  final IconData icon;
  bool selected;
}
