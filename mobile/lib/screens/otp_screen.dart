import 'dart:async';

import 'package:flutter/material.dart';

import '../l10n/strings.dart';
import '../models/task.dart';
import '../state/task_store.dart';
import '../theme/ethio_theme.dart';
import '../widgets/core.dart';
import '../widgets/otp_input.dart';

/// Human approval: enter the one-time code. Prototype accepts any 6 digits.
class OtpScreen extends StatefulWidget {
  const OtpScreen({super.key, required this.taskId});

  final String taskId;

  @override
  State<OtpScreen> createState() => _OtpScreenState();
}

class _OtpScreenState extends State<OtpScreen> {
  String _code = '';
  int _seconds = 30;
  Timer? _timer;
  String? _error;
  int _attempt = 0;

  @override
  void initState() {
    super.initState();
    _timer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (_seconds > 0) setState(() => _seconds--);
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  void _verify() {
    final s = S.of(context);
    if (_code.length < 6) {
      setState(() => _error = s.t('otp_error'));
      return;
    }
    final task = TaskStore.instance.taskById(widget.taskId)!;
    TaskStore.instance.approve(task, ApprovalKind.otp);
    Navigator.of(context).pop();
  }

  @override
  Widget build(BuildContext context) {
    final s = S.of(context);
    return ScreenScaffold(
      title: s.t('otp_title'),
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Container(
            width: 84,
            height: 84,
            decoration: const BoxDecoration(
              color: EthioColors.primarySoft,
              shape: BoxShape.circle,
            ),
            child: const Icon(Icons.sms_outlined,
                size: 40, color: EthioColors.primary),
          ),
          const SizedBox(height: 20),
          Text(s.t('otp_title'), style: EthioText.h2),
          const SizedBox(height: 8),
          Text(s.t('otp_body'), style: EthioText.bodyMuted),
          const SizedBox(height: 28),
          // Rebuilt per attempt so boxes clear on resend.
          OtpInput(
            key: ValueKey(_attempt),
            onCompleted: (code) => setState(() {
              _code = code;
              _error = null;
            }),
          ),
          if (_error != null) ...[
            const SizedBox(height: 12),
            Text(_error!,
                textAlign: TextAlign.center,
                style: const TextStyle(
                    color: EthioColors.danger,
                    fontWeight: FontWeight.w600)),
          ],
          const SizedBox(height: 28),
          EthioButton(
            label: s.t('otp_verify'),
            icon: Icons.verified_outlined,
            onPressed: _verify,
          ),
          const SizedBox(height: 12),
          Center(
            child: _seconds > 0
                ? Text(s.t('otp_resend_in', {'s': '$_seconds'}),
                    style: EthioText.small)
                : TextButton(
                    onPressed: () => setState(() {
                      _seconds = 30;
                      _attempt++;
                      _code = '';
                      _error = null;
                    }),
                    child: Text(s.t('otp_resend')),
                  ),
          ),
        ],
      ),
    );
  }
}
