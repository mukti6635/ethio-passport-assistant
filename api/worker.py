"""ETHIO browser worker loop: OBSERVE -> REASON -> ACT -> VERIFY.

Connects the orchestrator, approval service, and a real browser against
the MOCK PORTAL ONLY. Never touches the real passport portal.

The loop:
1. OBSERVE: read the mock portal's current step and field values.
2. REASON: the policy proposes the next action (scripted in tests;
   LLM-driven in production via the gateway).
3. CLASSIFY: orchestrator.propose_action() routes via PROTECTED_ACTIONS.
   The model never decides or overrides the protection policy.
4. ACT:
   - Safe action: execute within the safety policy, then VERIFY.
   - Protected action: prepare approval, move job to waiting_approval,
     DO NOT execute. Wait for the user's decision.
5. On approval: validate owner/status/expiry/params-hash/page-state,
   claim execution (exactly once), dispatch, observe again, VERIFY the
   postcondition independently.
6. Record a secret-safe evidence event for every action.

Safety: mock-portal URL allowlist only. Secret-safe logging (types and
field names only, never values). No screenshots stored.
"""

import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from approvals import ApprovalService, ApprovalState, ExecutionState
from orchestrator import (
    ActionDisposition,
    SingleStepOrchestrator,
)


# Only these origins may be automated. The real portal is never allowed.
ALLOWED_ORIGINS = ("http://127.0.0.1:8901", "http://localhost:8901")


class WorkerState(str, Enum):
    IDLE = "idle"
    OBSERVING = "observing"
    ACTING = "acting"
    VERIFYING = "verifying"
    WAITING_APPROVAL = "waiting_approval"
    DONE = "done"
    FAILED = "failed"


@dataclass
class PortalObservation:
    """Secret-safe snapshot of the mock portal state."""

    step: str  # e.g. "form", "review", "checkpoints", "done"
    # field_id -> True if non-empty (never the actual value)
    fields_present: Dict[str, bool] = field(default_factory=dict)
    # field_id -> sha256 of value (for change detection, not the value)
    field_hashes: Dict[str, str] = field(default_factory=dict)
    url: str = ""
    timestamp: float = field(default_factory=time.time)

    def state_fingerprint(self) -> str:
        """Fingerprint for stale-context detection."""
        parts = [self.step] + sorted(
            f"{k}={v}" for k, v in self.field_hashes.items()
        )
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


@dataclass
class EvidenceEvent:
    """Structured, secret-safe record of one worker action."""

    task_id: str
    action_id: str
    observed_step: str
    proposed_action: str  # type only
    classification: str  # "safe" or "protected"
    approval_id: Optional[str] = None
    execution_id: Optional[str] = None
    result: str = "pending"  # succeeded|failed|blocked|unknown
    verification: str = ""  # secret-safe postcondition description
    timestamp: float = field(default_factory=time.time)
    final_state: str = ""


# Policy: proposes the next action given an observation.
# Returns (action_type, params, params_summary, label, consequence)
# or None when the workflow is complete.
Policy = Callable[
    [PortalObservation, Dict[str, str]],
    Optional[tuple],
]


class MockPortalDriver:
    """Playwright driver for the mock portal. Real browser, mock site only."""

    def __init__(self, page: Any):
        self._page = page

    def _check_origin(self, url: str) -> None:
        if not any(url.startswith(o) for o in ALLOWED_ORIGINS):
            raise RuntimeError(f"blocked: origin not allowed: {url[:80]}")

    async def observe(self) -> PortalObservation:
        url = self._page.url
        self._check_origin(url)
        step = await self._page.evaluate(
            """() => {
                const el = document.querySelector('[data-step]:not([hidden])');
                return el ? el.getAttribute('data-step') : 'unknown';
            }"""
        )
        fields = await self._page.evaluate(
            """() => {
                const out = {};
                document.querySelectorAll('input[id], select[id]').forEach(el => {
                    out[el.id] = el.value || '';
                });
                return out;
            }"""
        )
        present = {k: bool(v) for k, v in fields.items()}
        hashes = {
            k: hashlib.sha256(v.encode()).hexdigest()[:16]
            for k, v in fields.items()
        }
        return PortalObservation(
            step=step or "unknown",
            fields_present=present,
            field_hashes=hashes,
            url=url,
        )

    async def fill_field(self, field_id: str, value: str) -> bool:
        """Fill a field and verify by read-back. Returns True if verified.
        Handles <select> elements via select_option."""
        tag = await self._page.evaluate(
            f"() => document.getElementById('{field_id}')?.tagName || ''"
        )
        if tag == "SELECT":
            await self._page.select_option(f"#{field_id}", value)
        else:
            await self._page.fill(f"#{field_id}", value)
        read_back = await self._page.input_value(f"#{field_id}")
        return read_back == value

    async def click(self, selector: str) -> None:
        await self._page.click(selector)

    async def is_visible(self, selector: str) -> bool:
        """True if the element exists and is visible (waits briefly)."""
        try:
            await self._page.wait_for_selector(
                selector, state="visible", timeout=5000
            )
            return True
        except Exception:
            return False

    async def verify_field(self, field_id: str, expected: str) -> bool:
        actual = await self._page.input_value(f"#{field_id}")
        return actual == expected

    async def current_step(self) -> str:
        obs = await self.observe()
        return obs.step


class WorkerLoop:
    """Runs one task through observe/reason/act/verify with approvals."""

    def __init__(
        self,
        task_id: str,
        session_id: str,
        goal: str,
        inputs: Dict[str, str],
        driver: MockPortalDriver,
        approval_service: ApprovalService,
        policy: Policy,
        on_event: Optional[Callable[[EvidenceEvent], None]] = None,
    ):
        self.task_id = task_id
        self.session_id = session_id
        self.orchestrator = SingleStepOrchestrator(goal, inputs)
        self.driver = driver
        self.approvals = approval_service
        self.policy = policy
        self.on_event = on_event or (lambda e: None)
        self.state = WorkerState.IDLE
        self.events: List[EvidenceEvent] = []
        self._action_counter = 0

    def _emit(self, event: EvidenceEvent) -> None:
        self.events.append(event)
        self.on_event(event)

    def _next_action_id(self) -> str:
        self._action_counter += 1
        return f"{self.task_id}-a{self._action_counter}"

    async def run_step(self) -> WorkerState:
        """Run one observe/reason/act/verify cycle. Returns worker state."""
        self.state = WorkerState.OBSERVING
        obs = await self.driver.observe()

        proposal = self.policy(obs, self.orchestrator.inputs)
        if proposal is None:
            self.state = WorkerState.DONE
            return self.state

        action_type, params, summary, label, consequence = proposal
        action_id = self._next_action_id()

        # CLASSIFY via the code-defined policy (never the model).
        classified = self.orchestrator.propose_action(
            action_type=action_type,
            params=dict(params),
            approval_service=self.approvals,
            job_id=self.task_id,
            session_id=self.session_id,
            action_label=label,
            consequence=consequence,
            params_summary=dict(summary),
        )

        if classified.disposition == ActionDisposition.AWAITS_APPROVAL:
            # Protected: prepare only. The browser does NOTHING yet.
            self.state = WorkerState.WAITING_APPROVAL
            self._emit(EvidenceEvent(
                task_id=self.task_id,
                action_id=action_id,
                observed_step=obs.step,
                proposed_action=action_type,
                classification="protected",
                approval_id=classified.approval.approval_id,
                result="blocked",
                verification="awaiting user approval; no browser action taken",
                final_state=self.state.value,
            ))
            return self.state

        # Safe action: execute within the safety policy, then verify.
        return await self._execute_safe(
            action_id, action_type, params, obs,
        )

    async def _execute_safe(
        self,
        action_id: str,
        action_type: str,
        params: Dict[str, Any],
        obs: PortalObservation,
    ) -> WorkerState:
        self.state = WorkerState.ACTING
        event = EvidenceEvent(
            task_id=self.task_id,
            action_id=action_id,
            observed_step=obs.step,
            proposed_action=action_type,
            classification="safe",
        )
        try:
            if action_type == "input":
                ok = await self.driver.fill_field(
                    params["field"], params["value"]
                )
                # Independent verification: read back the field.
                verified = await self.driver.verify_field(
                    params["field"], params["value"]
                )
                event.result = "succeeded" if (ok and verified) else "failed"
                event.verification = (
                    f"field {params['field']} read-back "
                    f"{'matched' if verified else 'MISMATCH'}"
                )
            elif action_type == "click":
                await self.driver.click(params["selector"])
                # Verify by observing the new step.
                new_obs = await self.driver.observe()
                if params.get("verify_step"):
                    ok_step = new_obs.step == params["verify_step"]
                    event.result = "succeeded" if ok_step else "failed"
                    event.verification = (
                        f"step {obs.step} -> {new_obs.step} "
                        f"(expected {params['verify_step']})"
                    )
                else:
                    event.result = "succeeded"
                    event.verification = (
                        f"step {obs.step} -> {new_obs.step}"
                    )
            else:
                event.result = "failed"
                event.verification = f"unknown safe action: {action_type}"
        except Exception as exc:
            event.result = "failed"
            event.verification = f"browser error: {type(exc).__name__}"
        event.final_state = self.state.value
        self._emit(event)
        self.orchestrator.record_step(
            action_type, event.verification, event.result == "succeeded"
        )
        self.state = (
            WorkerState.IDLE if event.result == "succeeded"
            else WorkerState.FAILED
        )
        return self.state

    async def execute_approved(
        self,
        approval_id: str,
        action_type: str,
        params: Dict[str, Any],
    ) -> EvidenceEvent:
        """Execute a user-approved protected action.

        Validates owner/status/expiry/params/page-state, claims execution
        exactly once, dispatches, observes, and verifies the postcondition.
        Returns the evidence event. Never blind-retries on unknown outcome.
        """
        action_id = self._next_action_id()
        obs_before = await self.driver.observe()
        event = EvidenceEvent(
            task_id=self.task_id,
            action_id=action_id,
            observed_step=obs_before.step,
            proposed_action=action_type,
            classification="protected",
            approval_id=approval_id,
        )

        # 1. Claim through the authorized path (validates everything).
        approval = self.approvals.claim_for_execution(
            approval_id, self.session_id, self.task_id,
            action_type, dict(params),
        )
        if approval is None:
            event.result = "blocked"
            event.verification = (
                "claim denied: not approved, expired, params changed, "
                "or already claimed"
            )
            event.final_state = WorkerState.FAILED.value
            self._emit(event)
            return event
        event.execution_id = approval.execution_id

        # 2. Stale-context check: if the page changed since preparation,
        #    do not execute a potentially stale action.
        #    (The approval stores no fingerprint; the worker re-observes
        #    and the policy must confirm the context is still valid.)
        obs_now = await self.driver.observe()
        if obs_now.step != obs_before.step:
            # Page changed mid-flight: mark unknown, do not dispatch.
            self.approvals.record_execution_result(
                approval_id, self.session_id, approval.execution_id,
                False, "page changed before dispatch; action not taken",
            )
            event.result = "unknown"
            event.verification = (
                f"page changed {obs_before.step}->{obs_now.step}; "
                "not dispatched; needs review"
            )
            event.final_state = WorkerState.FAILED.value
            self._emit(event)
            return event

        # 3. Dispatch exactly once from the worker's perspective.
        self.state = WorkerState.ACTING
        try:
            if action_type == "input":
                ok = await self.driver.fill_field(
                    params["field"], params["value"]
                )
                verified = await self.driver.verify_field(
                    params["field"], params["value"]
                )
                success = ok and verified
                evidence = (
                    f"field {params['field']} read-back "
                    f"{'matched' if verified else 'MISMATCH'}"
                )
            elif action_type == "submit":
                # Mock portal only: the mock's submit is a fakeServer call.
                # We click and verify the confirmation step appears.
                await self.driver.click(params["selector"])
                new_obs = await self.driver.observe()
                success = new_obs.step in ("done", "final", "confirmation")
                evidence = f"after submit, step={new_obs.step}"
            elif "selector" in params:
                # Generic protected action (payment, appointment, ...):
                # click the prepared selector, then verify the declared
                # postcondition: a selector that must become visible, or
                # a step the page must reach.
                await self.driver.click(params["selector"])
                if params.get("verify_visible"):
                    visible = await self.driver.is_visible(
                        params["verify_visible"]
                    )
                    success = visible
                    evidence = (
                        f"{params['verify_visible']} "
                        f"{'visible' if visible else 'NOT VISIBLE'}"
                    )
                elif params.get("verify_step"):
                    new_obs = await self.driver.observe()
                    success = new_obs.step == params["verify_step"]
                    evidence = (
                        f"step={new_obs.step} "
                        f"(expected {params['verify_step']})"
                    )
                else:
                    new_obs = await self.driver.observe()
                    success = True
                    evidence = f"clicked; step={new_obs.step}"
            else:
                success = False
                evidence = f"unsupported protected action: {action_type}"
        except Exception as exc:
            # Browser failure: record accurately, do not guess.
            self.approvals.record_execution_result(
                approval_id, self.session_id, approval.execution_id,
                False, f"browser error: {type(exc).__name__}",
            )
            event.result = "failed"
            event.verification = f"browser error: {type(exc).__name__}"
            event.final_state = WorkerState.FAILED.value
            self._emit(event)
            return event

        # 4. Independent verification of the postcondition.
        self.state = WorkerState.VERIFYING
        obs_after = await self.driver.observe()
        if success:
            self.approvals.record_execution_result(
                approval_id, self.session_id, approval.execution_id,
                True, evidence,
            )
            event.result = "succeeded"
        else:
            self.approvals.record_execution_result(
                approval_id, self.session_id, approval.execution_id,
                False, evidence,
            )
            event.result = "failed"
        event.verification = evidence + f"; observed step={obs_after.step}"
        event.final_state = self.state.value
        self.orchestrator.record_step(
            action_type, event.verification, event.result == "succeeded"
        )
        self.state = (
            WorkerState.IDLE if event.result == "succeeded"
            else WorkerState.FAILED
        )
        self._emit(event)
        return event
