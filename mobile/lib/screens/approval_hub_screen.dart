import 'dart:async';

import 'package:flutter/material.dart';

import '../backend/gateway_client.dart';
import '../backend/repository.dart';
import '../l10n/strings.dart';
import '../models/task.dart';
import '../state/task_store.dart';
import '../theme/ethio_theme.dart';
import '../widgets/backend_approval_card.dart';
import '../widgets/core.dart';

/// Human approval hub: OTP, CAPTCHA, payments and the final legal step.
/// The AI never passes these without the user.
///
/// Shows two sections:
/// 1. Local task approvals (existing flow).
/// 2. Backend approvals: server-enforced approval requests from the
///    gateway's approval service. Pass [gatewaySession] to enable; the
///    credential is resolved fresh from the signed-in user's session on
///    every refresh (see backend/gateway_client.dart). When the gateway
///    uses per-user auth and nobody is signed in, a sign-in form is
///    shown instead. When unconfigured, the section is hidden.
class ApprovalHubScreen extends StatelessWidget {
  const ApprovalHubScreen({
    super.key,
    required this.taskId,
    this.gatewaySession,
    this.auth,
  });

  final String taskId;

  /// Gateway session config (jwt or devkey). Null = not configured.
  final GatewaySessionConfig? gatewaySession;

  /// Auth repository used by the sign-in form (jwt mode). Null when
  /// Supabase is not configured.
  final AuthRepository? auth;

  @override
  Widget build(BuildContext context) {
    final s = S.of(context);
    return ListenableBuilder(
      listenable: TaskStore.instance,
      builder: (context, _) {
        final task = TaskStore.instance.taskById(taskId)!;
        final store = TaskStore.instance;
        final allApproved = task.approvals.isNotEmpty &&
            task.approvals.every((a) => a.approved);
        return ScreenScaffold(
          title: s.t('ap_title'),
          body: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(s.t('ap_sub'), style: EthioText.bodyMuted),
              const SizedBox(height: 16),
              for (final approval in task.approvals)
                _ApprovalTile(
                  approval: approval,
                  onTap: approval.approved
                      ? null
                      : () => Navigator.of(context).pushNamed(
                          _routeFor(approval.kind),
                          arguments: task.id),
                ),
              const SizedBox(height: 8),
              _BackendApprovalsSection(session: gatewaySession, auth: auth),
              const SizedBox(height: 12),
              Container(
                padding: const EdgeInsets.all(14),
                decoration: BoxDecoration(
                  color: EthioColors.bg,
                  borderRadius: BorderRadius.circular(14),
                  border: Border.all(color: EthioColors.line),
                ),
                child: Text(s.t('ap_hint'), style: EthioText.small),
              ),
              const SizedBox(height: 16),
              EthioButton(
                label: s.t('common_continue'),
                icon: Icons.arrow_forward,
                onPressed: allApproved
                    ? () {
                        final def = _defFor(task);
                        if (def) {
                          store.advanceStage(task, TaskStage.appointment);
                          Navigator.of(context)
                              .pushNamed('/appointments', arguments: task.id);
                        } else {
                          store.finishWithoutAppointment(task);
                          Navigator.of(context)
                              .pushNamedAndRemoveUntil('/', (r) => false);
                        }
                      }
                    : null,
              ),
            ],
          ),
        );
      },
    );
  }

  String _routeFor(ApprovalKind kind) {
    switch (kind) {
      case ApprovalKind.otp:
        return '/otp';
      case ApprovalKind.captcha:
        return '/captcha';
      case ApprovalKind.payment:
        return '/payment';
      case ApprovalKind.legal:
        return '/legal';
    }
  }

  bool _defFor(ServiceTask task) {
    // Only services that need an in-person visit go to appointments.
    const needs = {'passport', 'license', 'business'};
    return needs.contains(task.serviceId);
  }
}

/// Section showing server-enforced approval requests from the gateway.
///
/// The gateway credential is resolved fresh on every refresh from the
/// current session — never cached — so token refresh and sign-out take
/// effect immediately. Approvals live on the server, so reopening this
/// screen re-fetches the authoritative pending list. In jwt mode with
/// no signed-in user, a sign-in form replaces the list.
class _BackendApprovalsSection extends StatefulWidget {
  const _BackendApprovalsSection({required this.session, required this.auth});

  final GatewaySessionConfig? session;
  final AuthRepository? auth;

  @override
  State<_BackendApprovalsSection> createState() =>
      _BackendApprovalsSectionState();
}

class _BackendApprovalsSectionState extends State<_BackendApprovalsSection> {
  List<BackendApproval>? _approvals;
  BackendApprovalConfig? _config;
  String? _error;
  bool _loading = false;
  StreamSubscription<AuthSession?>? _authSub;

  @override
  void initState() {
    super.initState();
    // Session restored, token refreshed, signed in or out → re-resolve
    // the credential and re-fetch with the new identity.
    _authSub = widget.auth?.onAuthChanged.listen((_) => _refresh());
    _refresh();
  }

  @override
  void dispose() {
    _authSub?.cancel();
    super.dispose();
  }

  Future<void> _refresh() async {
    final session = widget.session;
    if (session == null) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final config = await session.currentConfig();
      if (!mounted) return;
      if (config == null) {
        // Jwt mode + signed out (or devkey without a credential).
        setState(() {
          _config = null;
          _approvals = null;
          _loading = false;
        });
        return;
      }
      final list = await GatewayTaskClient(config).listPendingApprovals();
      if (mounted) {
        setState(() {
          _config = config;
          _approvals = list;
          _loading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _error = e.toString();
          _loading = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final session = widget.session;
    if (session == null) {
      return const SizedBox.shrink();
    }
    final signedIn = widget.auth?.current;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          children: [
            const Expanded(
              child: Text('Server approvals', style: EthioText.smallBold),
            ),
            if (_loading)
              const SizedBox(
                width: 16,
                height: 16,
                child: CircularProgressIndicator(strokeWidth: 2),
              )
            else
              TextButton(
                onPressed: _refresh,
                child: const Text('Refresh'),
              ),
          ],
        ),
        if (session.requiresSignIn && signedIn == null) ...[
          if (widget.auth == null)
            const Text(
              'Supabase is not configured, so per-user sign-in is '
              'unavailable. See the setup notes in docs/DEVELOPMENT.md.',
              style: EthioText.caption,
            )
          else
            _SignInForm(auth: widget.auth!, onSignedIn: _refresh),
        ] else ...[
          if (signedIn != null)
            Row(
              children: [
                Expanded(
                  child: Text('Signed in as ${signedIn.email}',
                      style: EthioText.caption),
                ),
                TextButton(
                  onPressed: () async {
                    await widget.auth?.signOut();
                    _refresh();
                  },
                  child: const Text('Sign out'),
                ),
              ],
            ),
          if (_error != null) ...[
            Text(_error!, style: EthioText.caption),
            TextButton(onPressed: _refresh, child: const Text('Retry')),
          ] else if (_config == null || _approvals == null) ...[
            const Text('Loading server approvals…', style: EthioText.caption),
          ] else if (_approvals!.isEmpty) ...[
            const Text('No pending server approvals.',
                style: EthioText.caption),
          ] else ...[
            for (final a in _approvals!)
              BackendApprovalCard(
                approval: a,
                baseUrl: _config!.baseUrl,
                apiKey: _config!.apiKey,
                sessionId: _config!.sessionId,
                // Resolve the CURRENT config at tap time so a token
                // rotation since this list was fetched cannot fail
                // the decision with a stale credential (Phase 13).
                configResolver: () => session.currentConfig(),
                // After a verified decision, refresh so the list
                // reflects the server's authoritative state.
                onDecided: (_) => _refresh(),
              ),
          ],
        ],
        const SizedBox(height: 4),
      ],
    );
  }
}

/// Minimal email/password sign-in for the gateway's per-user mode.
/// Errors come from the auth repository with presentable messages;
/// the password is never stored or logged by the app.
class _SignInForm extends StatefulWidget {
  const _SignInForm({required this.auth, required this.onSignedIn});

  final AuthRepository auth;
  final Future<void> Function() onSignedIn;

  @override
  State<_SignInForm> createState() => _SignInFormState();
}

class _SignInFormState extends State<_SignInForm> {
  final _email = TextEditingController();
  final _password = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _email.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _signIn() async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await widget.auth.signInWithEmail(_email.text, _password.text);
      _password.clear();
      if (mounted) setState(() => _busy = false);
      await widget.onSignedIn();
    } catch (e) {
      if (mounted) {
        setState(() {
          _error = e.toString();
          _busy = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const Text(
          'Sign in to see and decide your server approvals. Your '
          'identity comes from this sign-in — approvals are tied to '
          'your account on the server.',
          style: EthioText.caption,
        ),
        const SizedBox(height: 8),
        TextField(
          controller: _email,
          keyboardType: TextInputType.emailAddress,
          decoration: const InputDecoration(labelText: 'Email'),
        ),
        const SizedBox(height: 8),
        TextField(
          controller: _password,
          obscureText: true,
          decoration: const InputDecoration(labelText: 'Password'),
        ),
        if (_error != null) ...[
          const SizedBox(height: 8),
          Text(_error!,
              style: EthioText.caption.copyWith(color: EthioColors.danger)),
        ],
        const SizedBox(height: 10),
        EthioButton(
          label: _busy ? 'Signing in…' : 'Sign in',
          onPressed: _busy ? null : _signIn,
        ),
      ],
    );
  }
}

class _ApprovalTile extends StatelessWidget {
  const _ApprovalTile({required this.approval, required this.onTap});

  final ApprovalItem approval;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final s = S.of(context);
    final meta = _meta(approval.kind);
    return Card(
      color: Colors.white,
      elevation: 0,
      margin: const EdgeInsets.only(bottom: 12),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(18),
        side: const BorderSide(color: EthioColors.line),
      ),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(18),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Row(
            children: [
              Container(
                width: 52,
                height: 52,
                decoration: BoxDecoration(
                  color: approval.approved
                      ? EthioColors.okSoft
                      : EthioColors.primarySoft,
                  borderRadius: BorderRadius.circular(14),
                ),
                child: Icon(meta.$1,
                    color: approval.approved
                        ? EthioColors.ok
                        : EthioColors.primary,
                    size: 28),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(meta.$2, style: EthioText.smallBold),
                    const SizedBox(height: 4),
                    approval.approved
                        ? StatusChip.ok(s.t('ap_approved'), icon: Icons.check)
                        : StatusChip.warn(s.t('ap_pending'),
                            icon: Icons.hourglass_empty_outlined),
                  ],
                ),
              ),
              if (!approval.approved)
                TextButton(
                  onPressed: onTap,
                  child: Text(s.t('ap_open')),
                )
              else
                const Icon(Icons.check_circle, color: EthioColors.ok),
            ],
          ),
        ),
      ),
    );
  }

  (IconData, String) _meta(ApprovalKind kind) {
    switch (kind) {
      case ApprovalKind.otp:
        return (Icons.sms_outlined, 'Verification code');
      case ApprovalKind.captcha:
        return (Icons.shield_outlined, 'Security check');
      case ApprovalKind.payment:
        return (Icons.payments_outlined, 'Payment');
      case ApprovalKind.legal:
        return (Icons.gavel_outlined, 'Final legal review');
    }
  }
}
