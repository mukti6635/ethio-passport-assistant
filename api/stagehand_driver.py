"""Optional Stagehand v4 driver adapter for ETHIO (EXPERIMENTAL).

Implements the same surface the WorkerLoop needs (observe / fill_field /
click / verify_field / is_visible) on top of the Stagehand v4 Python SDK
in LOCAL mode. Selected only when ETHIO_BROWSER_DRIVER=stagehand; the
default remains the Playwright MockPortalDriver.

Security boundary (unchanged):
- ETHIO owns policy: PROTECTED_ACTIONS classification, approvals, and
  the execution lifecycle live in orchestrator.py / approvals.py. This
  adapter only executes what the WorkerLoop already authorized.
- The origin allowlist is enforced here exactly as in the Playwright
  driver; navigation outside it raises before any page action.
- The LLM is supplied as a client callback (BYO model): Stagehand's
  observe() never receives ETHIO credentials beyond the callback, and
  observe is used ONLY to locate elements for SAFE actions. Protected
  actions never go through act()/observe() dispatch.

Requirements: pip package `stagehand` (v4), a Chromium build with
extension support (Playwright's full chromium, NOT the headless shell),
and an LLM for observe(). Deterministic operations (fill/click/verify)
need no LLM and no Browserbase account.
"""

import hashlib
import os
import time
from typing import Any, Dict, Optional

from worker import ALLOWED_ORIGINS, PortalObservation

try:
    from stagehand import Stagehand, local_browser

    STAGEHAND_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    STAGEHAND_AVAILABLE = False


def _default_chrome_path() -> Optional[str]:
    """Locate a Chromium build that supports extensions."""
    env = os.environ.get("CHROME_PATH")
    if env:
        return env
    base = os.path.expanduser("~/.cache/ms-playwright")
    if os.path.isdir(base):
        for name in sorted(os.listdir(base)):
            if name.startswith("chromium-"):  # full build, not headless shell
                candidate = os.path.join(base, name, "chrome-linux", "chrome")
                if os.path.isfile(candidate):
                    return candidate
    return None


class StagehandPortalDriver:
    """Stagehand-backed driver with the MockPortalDriver interface.

    Owns its own browser session (Stagehand claims the browser), so it
    must not share a page with the Playwright driver. One driver per
    task, created via `await StagehandPortalDriver.start(...)`.
    """

    def __init__(self, stagehand: Any, page: Any):
        self._sh = stagehand
        self._page = page
        self.llm_stats = {"calls": 0, "input_tokens": 0, "output_tokens": 0}

    @classmethod
    async def start(
        cls,
        llm_callback=None,
        chrome_path: Optional[str] = None,
    ) -> "StagehandPortalDriver":
        if not STAGEHAND_AVAILABLE:
            raise RuntimeError(
                "stagehand package not installed; "
                "pip install stagehand (v4) to use this driver"
            )
        chrome = chrome_path or _default_chrome_path()
        if not chrome:
            raise RuntimeError(
                "no extension-capable Chromium found; set CHROME_PATH"
            )
        browser = await local_browser.launch(
            headless=True, executable_path=chrome
        )
        kwargs: Dict[str, Any] = {"browser": browser}
        if llm_callback is not None:
            kwargs["model"] = llm_callback
        sh = await Stagehand.create(**kwargs)
        page = await browser.context.new_page()
        driver = cls(sh, page)
        driver._browser = browser
        return driver

    async def close(self) -> None:
        try:
            await self._sh.close()
        finally:
            await self._browser.close()

    # -- driver interface (mirrors MockPortalDriver) ---------------------

    def _check_origin(self, url: str) -> None:
        if not any(url.startswith(o) for o in ALLOWED_ORIGINS):
            raise RuntimeError(f"blocked: origin not allowed: {url[:80]}")

    async def goto(self, url: str) -> None:
        self._check_origin(url)
        await self._page.goto(url)

    async def observe(self) -> PortalObservation:
        url = await self._page.evaluate("window.location.href")
        self._check_origin(url)
        step = await self._page.evaluate(
            "(() => { const el = document.querySelector("
            "'[data-step]:not([hidden])'); return el ? "
            "el.getAttribute('data-step') : 'unknown'; })()"
        )
        fields = await self._page.evaluate(
            "(() => { const out = {}; document.querySelectorAll("
            "'input[id], select[id]').forEach(el => { "
            "out[el.id] = el.value || ''; }); return out; })()"
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
        tag = await self._page.evaluate(
            f"document.getElementById('{field_id}')?.tagName || ''"
        )
        loc = self._page.locator(f"#{field_id}")
        if tag == "SELECT":
            await loc.select_option(value)
        else:
            await loc.fill(value)
        read_back = await loc.input_value()
        return read_back == value

    async def click(self, selector: str) -> None:
        await self._page.locator(selector).click()

    async def is_visible(self, selector: str) -> bool:
        try:
            await self._page.locator(selector).wait_for(
                state="visible", timeout=5000
            )
            return True
        except Exception:
            return False

    async def verify_field(self, field_id: str, expected: str) -> bool:
        actual = await self._page.locator(f"#{field_id}").input_value()
        return actual == expected

    async def current_step(self) -> str:
        obs = await self.observe()
        return obs.step

    # -- Stagehand-only capability: LLM element resolution ---------------

    async def resolve_locator(self, instruction: str):
        """Use Stagehand observe() to resolve a natural-language target.

        Returns the observe result (actions with selectors) or raises.
        Used only for SAFE actions; protected actions always use the
        exact prepared selector from the approval.
        """
        return await self._sh.observe(instruction, page=self._page)
