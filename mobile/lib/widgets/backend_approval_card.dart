import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import '../backend/gateway_client.dart';
import '../theme/ethio_theme.dart';
import '../widgets/core.dart';

export '../backend/gateway_client.dart'
    show BackendApproval, BackendApprovalConfig;

/// Convenience wrapper kept for compatibility: builds a one-shot
/// [GatewayTaskClient] from raw connection values. New code should
/// resolve a fresh config via GatewaySessionConfig and use the client
/// directly, so refreshed tokens are picked up.
Future<BackendApproval?> decideBackendApproval({
  required String baseUrl,
  required String apiKey,
  required String sessionId,
  required String approvalId,
  required bool approve,
  String? reason,
  http.Client? client,
}) {
  final gateway = GatewayTaskClient(
    BackendApprovalConfig(
        baseUrl: baseUrl, apiKey: apiKey, sessionId: sessionId),
    client: client,
  );
  return gateway.decideApproval(approvalId, approve: approve, reason: reason);
}

/// Fetches this user's pending approvals from the backend.
Future<List<BackendApproval>> fetchPendingApprovals({
  required String baseUrl,
  required String apiKey,
  required String sessionId,
  http.Client? client,
}) {
  final gateway = GatewayTaskClient(
    BackendApprovalConfig(
        baseUrl: baseUrl, apiKey: apiKey, sessionId: sessionId),
    client: client,
  );
  return gateway.listPendingApprovals();
}

/// A card showing one backend approval request with Approve / Reject.
/// Displays the backend's verified decision result — never assumes success.
class BackendApprovalCard extends StatefulWidget {
  const BackendApprovalCard({
    super.key,
    required this.approval,
    required this.baseUrl,
    required this.apiKey,
    required this.sessionId,
    this.onDecided,
    this.httpClient,
    this.configResolver,
  });

  final BackendApproval approval;
  final String baseUrl;
  final String apiKey;
  final String sessionId;
  final void Function(BackendApproval result)? onDecided;

  /// Test seam: inject a mock HTTP client. Null in production.
  final http.Client? httpClient;

  /// Optional fresh-config resolver (Phase 13). The baseUrl/apiKey/
  /// sessionId props are a snapshot from when the list was fetched;
  /// access tokens rotate (hourly), so a decision tapped after a
  /// rotation would carry a stale credential and fail with a 401.
  /// When a resolver is provided, the card resolves the CURRENT
  /// config at tap time and uses it instead of the snapshot. A null
  /// result means "signed out meanwhile" and is shown honestly.
  final Future<BackendApprovalConfig?> Function()? configResolver;

  @override
  State<BackendApprovalCard> createState() => _BackendApprovalCardState();
}

class _BackendApprovalCardState extends State<BackendApprovalCard> {
  bool _busy = false;
  String? _error;
  BackendApproval? _result;
  bool _lastApprove = true; // direction of the last attempt (for Retry)

  Future<void> _decide(bool approve) async {
    if (_busy) return; // prevent duplicate submissions
    setState(() {
      _busy = true;
      _error = null;
      _lastApprove = approve;
    });
    try {
      // Prefer a freshly resolved config (current token) over the
      // snapshot this card was built with.
      var baseUrl = widget.baseUrl;
      var apiKey = widget.apiKey;
      var sessionId = widget.sessionId;
      final resolver = widget.configResolver;
      if (resolver != null) {
        final fresh = await resolver();
        if (fresh == null) {
          throw GatewayException(
              401, 'Signed out — refresh the list and sign in again.');
        }
        baseUrl = fresh.baseUrl;
        apiKey = fresh.apiKey;
        sessionId = fresh.sessionId;
      }
      final result = await decideBackendApproval(
        baseUrl: baseUrl,
        apiKey: apiKey,
        sessionId: sessionId,
        approvalId: widget.approval.approvalId,
        approve: approve,
        client: widget.httpClient,
      );
      if (!mounted) return;
      // Reflect the backend's verified response, not the tap.
      setState(() {
        _result = result;
        _busy = false;
      });
      if (result != null) widget.onDecided?.call(result);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString();
        _busy = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final approval = _result ?? widget.approval;
    final decided = _result != null || !approval.isPending;
    return Card(
      color: Colors.white,
      elevation: 0,
      margin: const EdgeInsets.only(bottom: 12),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(18),
        side: const BorderSide(color: EthioColors.line),
      ),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                Container(
                  width: 48,
                  height: 48,
                  decoration: BoxDecoration(
                    color: decided ? EthioColors.okSoft : EthioColors.warnSoft,
                    borderRadius: BorderRadius.circular(14),
                  ),
                  child: Icon(
                    decided ? Icons.check_circle : Icons.hourglass_empty,
                    color: decided ? EthioColors.ok : EthioColors.warn,
                    size: 26,
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(approval.actionLabel, style: EthioText.smallBold),
                      const SizedBox(height: 2),
                      Text(
                        'Expires ${approval.expiresAt.toLocal()}'
                            .split('.')
                            .first,
                        style: EthioText.caption,
                      ),
                    ],
                  ),
                ),
                decided
                    ? (approval.state == 'approved'
                        ? StatusChip.ok(approval.state)
                        : StatusChip.danger(approval.state))
                    : StatusChip.warn('pending'),
              ],
            ),
            const SizedBox(height: 10),
            Text(approval.consequence, style: EthioText.body),
            if (approval.paramsSummary.isNotEmpty) ...[
              const SizedBox(height: 8),
              for (final e in approval.paramsSummary.entries)
                Padding(
                  padding: const EdgeInsets.only(bottom: 2),
                  child: Text('${e.key}: ${e.value}', style: EthioText.caption),
                ),
            ],
            if (_error != null) ...[
              const SizedBox(height: 8),
              Text(_error!,
                  style: EthioText.caption.copyWith(color: EthioColors.danger)),
              TextButton(
                // Retry repeats the SAME decision the user chose —
                // never silently flips a rejection into an approval.
                onPressed: _busy ? null : () => _decide(_lastApprove),
                child: const Text('Retry'),
              ),
            ],
            if (!decided) ...[
              const SizedBox(height: 12),
              Row(
                children: [
                  Expanded(
                    child: EthioButton(
                      label: 'Reject',
                      onPressed: _busy ? null : () => _decide(false),
                      secondary: true,
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: EthioButton(
                      label: _busy ? 'Working…' : 'Approve',
                      onPressed: _busy ? null : () => _decide(true),
                    ),
                  ),
                ],
              ),
            ] else ...[
              const SizedBox(height: 8),
              Text(
                'Decision recorded: ${approval.state}. '
                'The backend verified this result.',
                style: EthioText.caption,
              ),
            ],
          ],
        ),
      ),
    );
  }
}
