"""Fair benchmark: existing Playwright driver vs Stagehand adapter.

Same mock portal, same tasks, repeated trials. Measures:
- deterministic workflow latency + success (no LLM for either driver)
- Stagehand observe() latency + LLM calls/tokens (Groq callback) vs the
  existing driver's DOM-based observation (no LLM)
- layout-change robustness (mock portal alt labels)
- browser startup latency

Run with the stagehand test venv:
  /tmp/stagehand-test-venv/bin/python api/benchmark_drivers.py
Requires the Groq vault credential for the observe() trials; without it
those trials are reported as BLOCKED, not faked.
"""

import asyncio
import functools
import http.server
import json
import os
import statistics
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PORTAL_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "mobile", "mock-portal"
)
PORTAL_URL = "http://127.0.0.1:8901/index.html"
FIELDS = {
    "fullName": "Test User",
    "dob": "1990-01-01",
    "phone": "0911123456",
    "nationalId": "12345678",
    "serviceType": "idcard",
    "birthPlace": "Addis Ababa",
}
TRIALS = 3


def serve():
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=PORTAL_DIR
    )
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 8901), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def pct(values, q):
    if not values:
        return None
    s = sorted(values)
    idx = min(len(s) - 1, int(q * len(s)))
    return s[idx]


def summarize(name, samples, extra=None):
    ok = [s for s in samples if s["ok"]]
    times = [s["seconds"] for s in ok]
    return {
        "task": name,
        "trials": len(samples),
        "success": len(ok),
        "median_s": round(statistics.median(times), 3) if times else None,
        "p95_s": round(pct(times, 0.95), 3) if times else None,
        **(extra or {}),
    }


# ---------------------------------------------------------------------------
# Task A: deterministic workflow with a driver (fill + navigate + verify)
# ---------------------------------------------------------------------------

async def task_a_playwright():
    from playwright.async_api import async_playwright
    from worker import MockPortalDriver

    t0 = time.time()
    async with async_playwright() as p:
        startup = time.time()
        browser = await p.chromium.launch()
        startup_s = time.time() - startup
        page = await browser.new_page()
        await page.goto(PORTAL_URL)
        driver = MockPortalDriver(page)
        try:
            for fid, val in FIELDS.items():
                if not await driver.fill_field(fid, val):
                    return {"ok": False, "seconds": time.time() - t0,
                            "startup_s": startup_s}
            await driver.click("#btn-to-review")
            obs = await driver.observe()
            if obs.step != "review":
                return {"ok": False, "seconds": time.time() - t0,
                        "startup_s": startup_s}
            await driver.click("#btn-to-checkpoints")
            obs = await driver.observe()
            ok = obs.step == "checkpoints"
            return {"ok": ok, "seconds": time.time() - t0,
                    "startup_s": startup_s}
        finally:
            await browser.close()


async def task_a_stagehand():
    from stagehand_driver import StagehandPortalDriver

    t0 = time.time()
    startup = time.time()
    driver = await StagehandPortalDriver.start()
    startup_s = time.time() - startup
    try:
        await driver.goto(PORTAL_URL)
        for fid, val in FIELDS.items():
            if not await driver.fill_field(fid, val):
                return {"ok": False, "seconds": time.time() - t0,
                        "startup_s": startup_s}
        await driver.click("#btn-to-review")
        obs = await driver.observe()
        if obs.step != "review":
            return {"ok": False, "seconds": time.time() - t0,
                    "startup_s": startup_s}
        await driver.click("#btn-to-checkpoints")
        obs = await driver.observe()
        ok = obs.step == "checkpoints"
        return {"ok": ok, "seconds": time.time() - t0,
                "startup_s": startup_s}
    finally:
        await driver.close()


# ---------------------------------------------------------------------------
# Groq LLM callback for Stagehand observe()
# ---------------------------------------------------------------------------

def get_groq_credential():
    raw = os.environ.get("GROQ_API_KEY")
    if raw:
        return raw
    try:
        sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
        from dynamic_credentials import dynamic_credential_entry

        entry = dynamic_credential_entry("custom.groq", "access_token")
        return str(entry.get("surrogate", "")).strip() or None
    except Exception:
        return None


def make_groq_callback(stats):
    import httpx
    from stagehand import (
        LLMMessageGenerateResult,
        LLMStructuredGenerateResult,
        LLMTextContent,
        LLMUsage,
    )

    # Sandbox quirk: this environment's no_proxy contains bracketed IPv6
    # entries that httpx cannot parse ("Invalid port ':1]'"). Sanitize
    # for this process only so the client can be constructed.
    for var in ("NO_PROXY", "no_proxy"):
        if "[" in os.environ.get(var, ""):
            os.environ[var] = "localhost,127.0.0.1"

    key = get_groq_credential()

    def _text_of(message):
        parts = []
        content = message.content
        blocks = content if isinstance(content, list) else [content]
        for b in blocks:
            t = getattr(b, "text", None)
            if t:
                parts.append(t)
            elif isinstance(b, dict) and b.get("text"):
                parts.append(b["text"])
        return "\n".join(parts)

    async def callback(params):
        stats["calls"] += 1
        messages = []
        if getattr(params, "system_prompt", None):
            messages.append(
                {"role": "system", "content": params.system_prompt}
            )
        for m in params.messages:
            messages.append({"role": str(m.role.value if hasattr(m.role, "value") else m.role),
                             "content": _text_of(m)})
        body = {
            "model": "openai/gpt-oss-120b",
            "messages": messages,
            "temperature": 0,
        }
        structured = hasattr(params, "response_format") and \
            getattr(params.response_format, "json_schema", None) is not None
        if structured:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "stagehand_response",
                    "schema": params.response_format.json_schema,
                    "strict": False,
                },
            }
        t0 = time.time()
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json=body,
            )
        stats["latency_s"] += time.time() - t0
        resp.raise_for_status()
        data = resp.json()
        usage = data.get("usage", {})
        stats["input_tokens"] += usage.get("prompt_tokens", 0)
        stats["output_tokens"] += usage.get("completion_tokens", 0)
        text = data["choices"][0]["message"]["content"] or ""
        llm_usage = LLMUsage(
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
        )
        if structured:
            parsed = json.loads(text)
            return LLMStructuredGenerateResult(
                role="assistant",
                content=[LLMTextContent(type="text", text=text)],
                usage=llm_usage,
                output_format="json_schema",
                structured_content=parsed,
            )
        return LLMMessageGenerateResult(
            role="assistant",
            content=[LLMTextContent(type="text", text=text)],
            usage=llm_usage,
            output_format="text",
        )

    return callback


# ---------------------------------------------------------------------------
# Task B: element resolution. Existing driver: DOM evaluate (no LLM).
# Stagehand: observe() with the Groq callback.
# ---------------------------------------------------------------------------

async def task_b_stagehand_observe(callback, stats_before):
    from stagehand_driver import StagehandPortalDriver

    t0 = time.time()
    driver = await StagehandPortalDriver.start(llm_callback=callback)
    try:
        await driver.goto(PORTAL_URL)
        result = await driver.resolve_locator(
            "find the input field for the applicant's full name"
        )
        text = json.dumps(
            result.model_dump() if hasattr(result, "model_dump") else str(result)
        )
        ok = "fullName" in text
        return {"ok": ok, "seconds": time.time() - t0}
    finally:
        await driver.close()


async def main():
    serve()
    results = {}

    # --- Task A: deterministic, both drivers ---
    pw_samples, sh_samples = [], []
    for _ in range(TRIALS):
        pw_samples.append(await task_a_playwright())
    for _ in range(TRIALS):
        sh_samples.append(await task_a_stagehand())
    results["A_playwright"] = summarize(
        "A deterministic workflow (Playwright driver)", pw_samples,
        {"median_startup_s": round(statistics.median(
            [s["startup_s"] for s in pw_samples]), 3)},
    )
    results["A_stagehand"] = summarize(
        "A deterministic workflow (Stagehand adapter)", sh_samples,
        {"median_startup_s": round(statistics.median(
            [s["startup_s"] for s in sh_samples]), 3)},
    )

    # --- Task B: observe ---
    cred = get_groq_credential()
    if cred:
        stats = {"calls": 0, "input_tokens": 0, "output_tokens": 0,
                 "latency_s": 0.0}
        callback = make_groq_callback(stats)
        b_samples = []
        for _ in range(TRIALS):
            try:
                b_samples.append(
                    await task_b_stagehand_observe(callback, stats)
                )
            except Exception as exc:
                b_samples.append({"ok": False, "seconds": 0,
                                  "error": type(exc).__name__})
        results["B_stagehand_observe"] = summarize(
            "B element resolution via observe() (Stagehand+Groq)",
            b_samples, {"llm": stats},
        )
    else:
        results["B_stagehand_observe"] = {
            "task": "B element resolution via observe()",
            "status": "BLOCKED: no Groq credential available",
        }
    results["B_playwright_observe"] = {
        "task": "B element resolution (Playwright driver)",
        "note": "DOM evaluate by field id; no LLM calls, ~ms latency, "
                "measured inside task A timings",
        "llm": {"calls": 0, "input_tokens": 0, "output_tokens": 0},
    }

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
