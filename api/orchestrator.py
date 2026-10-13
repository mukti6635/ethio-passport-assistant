"""Gateway-orchestrated single-step browser actions (prototype).

Unlike the standard browser-use Agent which plans multiple steps internally,
this orchestrator keeps workflow state in the gateway and asks the LLM for
only ONE action at a time. After each action, the gateway independently
verifies the result before proceeding.

Safety properties preserved:
- Mock portal only (URL allowlist)
- Never submits forms (action filter)
- Checkpoints (OTP/CAPTCHA/payment/appointment/submit) require explicit user action
- Secret-safe logging (action types only, never values)
- Bounded retries and safe stop on stagnation
"""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class OrchestratorState(str, Enum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    STALLED = "stalled"  # bounded recovery exhausted
    AWAITING_HUMAN = "awaiting_human"  # checkpoint reached


# Actions that are never auto-executed; they require explicit user checkpoint.
PROTECTED_ACTIONS = frozenset({
    "submit",  # form submission
    "otp", "captcha",  # verification challenges
    "payment", "pay",  # payments
    "appointment", "book",  # appointment selection
})

# Maximum single-step attempts before safe stop.
MAX_STEP_ATTEMPTS = 3
# Maximum consecutive stagnant observations before stopping.
MAX_STAGNANT = 3


class ActionDisposition(str, Enum):
    """How the gateway must handle a model-proposed action."""
    EXECUTE_NOW = "execute_now"  # safe action; gateway may run it
    AWAITS_APPROVAL = "awaits_approval"  # protected; approval prepared


@dataclass
class ProposedAction:
    """Result of classifying a model-proposed action."""
    disposition: ActionDisposition
    action_type: str  # type only, never values
    approval: Optional[Any] = None  # Approval object when AWAITS_APPROVAL


@dataclass
class WorkflowStep:
    """One verified step in the orchestrated workflow."""
    step_no: int
    action_type: str  # e.g. "input", "click", "navigate" (type only, never values)
    verified: bool
    observation_hash: str  # to detect stagnation
    timestamp: float = field(default_factory=time.time)


@dataclass
class OrchestratorResult:
    state: OrchestratorState
    steps: List[WorkflowStep]
    verified_fields: Dict[str, str]  # field name -> verified value (test data only)
    error: Optional[str] = None
    checkpoint: Optional[str] = None


class SingleStepOrchestrator:
    """Gateway-owned workflow controller for single-step browser actions.

    The LLM proposes one action at a time. The gateway executes, observes,
    verifies, and updates state. The model never maintains a multi-step plan.
    """

    def __init__(
        self,
        goal: str,
        inputs: Dict[str, str],
        max_steps: int = 10,
    ):
        self.goal = goal
        self.inputs = dict(inputs)
        self.max_steps = max_steps
        self.steps: List[WorkflowStep] = []
        self.verified_fields: Dict[str, str] = {}
        self._stagnant_count = 0
        self._last_observation_hash = ""
        self._failed_attempts = 0

    def _hash_observation(self, observation: str) -> str:
        """Simple hash for stagnation detection (not cryptographic)."""
        import hashlib
        return hashlib.md5(observation.encode()[:2000]).hexdigest()[:16]

    def _is_protected_action(self, action_type: str) -> bool:
        """Check if an action requires human checkpoint."""
        action_lower = action_type.lower()
        return any(p in action_lower for p in PROTECTED_ACTIONS)

    def record_step(
        self,
        action_type: str,
        observation: str,
        verified: bool,
        field_name: Optional[str] = None,
        field_value: Optional[str] = None,
    ) -> OrchestratorState:
        """Record a completed step and update workflow state.

        Returns the new orchestrator state. Secret-safe: logs action types
        only, never parameter values.
        """
        obs_hash = self._hash_observation(observation)

        # Stagnation detection: same observation repeatedly
        if obs_hash == self._last_observation_hash:
            self._stagnant_count += 1
        else:
            self._stagnant_count = 0
            self._last_observation_hash = obs_hash

        step = WorkflowStep(
            step_no=len(self.steps) + 1,
            action_type=action_type,  # type only, never values
            verified=verified,
            observation_hash=obs_hash,
        )
        self.steps.append(step)

        # Update verified fields (for test data only; real PII never stored here)
        if verified and field_name and field_value:
            self.verified_fields[field_name] = field_value

        # State transitions
        if self._is_protected_action(action_type):
            return OrchestratorState.AWAITING_HUMAN

        if not verified:
            self._failed_attempts += 1
            if self._failed_attempts >= MAX_STEP_ATTEMPTS:
                return OrchestratorState.FAILED
            # Allow retry (bounded)
            return OrchestratorState.RUNNING

        # Reset failure count on verified step
        self._failed_attempts = 0

        if self._stagnant_count >= MAX_STAGNANT:
            return OrchestratorState.STALLED

        if len(self.steps) >= self.max_steps:
            return OrchestratorState.FAILED  # budget exhausted

        return OrchestratorState.RUNNING

    def should_continue(self, state: OrchestratorState) -> bool:
        """Whether the workflow should proceed to the next step."""
        return state == OrchestratorState.RUNNING

    def propose_action(
        self,
        action_type: str,
        params: Dict[str, Any],
        approval_service: Any,
        job_id: str,
        session_id: str,
        action_label: str,
        consequence: str,
        params_summary: Optional[Dict[str, str]] = None,
    ) -> "ProposedAction":
        """Classify a model-proposed action and route it correctly.

        - Non-protected actions: returned as EXECUTE_NOW; the gateway may
          run them directly.
        - Protected actions: the model NEVER executes these. Instead an
          approval is prepared via the approval service and the result is
          AWAITS_APPROVAL. The gateway moves the job to waiting_approval.

        Classification is explicit (PROTECTED_ACTIONS set) — the model
        does not decide whether a checkpoint is required.

        If the page state or parameters changed since a previous
        preparation for the same action, the caller must pass the new
        params: the idempotency key differs, so a FRESH approval is
        prepared and the old one is left to expire. Never reuse a stale
        approval for changed parameters.
        """
        if self._is_protected_action(action_type):
            approval = approval_service.prepare(
                job_id=job_id,
                session_id=session_id,
                action_type=action_type,
                action_label=action_label,
                consequence=consequence,
                params=dict(params),
                params_summary=dict(params_summary or {}),
            )
            return ProposedAction(
                disposition=ActionDisposition.AWAITS_APPROVAL,
                action_type=action_type,
                approval=approval,
            )
        return ProposedAction(
            disposition=ActionDisposition.EXECUTE_NOW,
            action_type=action_type,
            approval=None,
        )

    def get_summary(self) -> Dict[str, Any]:
        """Secret-safe summary for logging and tests."""
        return {
            "goal": self.goal[:100],
            "steps_completed": len(self.steps),
            "verified_fields": list(self.verified_fields.keys()),  # names only
            "stagnant_count": self._stagnant_count,
            "failed_attempts": self._failed_attempts,
        }
