"""
claude_agent.py — diagnose and fix a production incident with the Claude Agent SDK.

Two entry points:
  - run_agent()  (Phase 4) — DIAGNOSE only, with read-only tools (Read/Grep/Glob),
    so the diagnosis is grounded in the actual code and cites a real file:line.
  - run_fix()    (Phase 5) — FIX: widens the tool set to Edit/Write/Bash, applies
    a minimal fix, writes a TestNG regression test, runs `./mvnw test`, and
    reports whether the build went green. Never commits/pushes — a human reviews
    the PR that github_client opens.

Authentication is whatever the Claude Agent SDK (i.e. the Claude Code engine)
is configured with, in this order of convenience:
  - a local Claude Code login (keyless — no API key needed), or
  - ANTHROPIC_API_KEY, or
  - a corporate gateway / Bedrock / Vertex via the usual env vars.
If the SDK is unavailable or returns no parseable JSON, both entry points
degrade to a deterministic local diagnosis tagged source="fallback" (run_fix
also sets fix_applied=False), so the degradation is never silent — important
for headless CI.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path

from rich.console import Console

from config import config

console = Console()

AUTOPILOT_DIR = Path(__file__).resolve().parent
# The code tree the agent reads to ground its diagnosis. Override with
# TARGET_REPO_DIR to point AutoFix at another team's service (defaults to the
# bundled demo backend).
BACKEND_DIR = Path(os.environ.get("TARGET_REPO_DIR", str(AUTOPILOT_DIR.parent / "backend"))).resolve()

SYSTEM_PROMPT = (
    "You are an on-call SRE for a K-8 education platform (Spring Boot + Maven + "
    "TestNG). You are given one production exception. Read the relevant source "
    "to find the root cause. Do NOT edit any files — diagnosis only. Cite the "
    "exact file and line. Be concise and specific."
)

PROMPT_TEMPLATE = """\
A production exception was detected. Diagnose the root cause by reading the
relevant source under src/main/java/com/example/studentprogress/.

INCIDENT
- Exception: {exception_class}
- Message  : {message}
- Location : {file}:{line}
- Request  : {request_params}

Traceback:
{traceback_text}

When done, output ONLY a fenced ```json block with exactly these keys:
{{
  "root_cause": "<one or two sentences; cite file:line>",
  "steps_to_reproduce": ["<step 1>", "<step 2>", "..."],
  "files_changed": ["<files you would change to fix it>"],
  "fix_description": "<the minimal fix you recommend>",
  "test_added": "<name of the regression test you would add>",
  "acceptance_criteria": ["<testable condition for done>", "..."],
  "confidence": <integer 1-5>
}}
"""


def _build_prompt(incident: dict) -> str:
    return PROMPT_TEMPLATE.format(
        exception_class=incident.get("exception_class", ""),
        message=incident.get("message") or incident.get("exception_message") or "",
        file=incident.get("file", ""),
        line=incident.get("line", ""),
        request_params=(
            incident.get("request_params")
            or f"studentId={incident.get('student_id')}, academicYear={incident.get('academic_year')}"
        ),
        traceback_text=incident.get("traceback_text") or incident.get("traceback") or "",
    )


def _extract_json(text: str) -> dict | None:
    """Pull the final fenced (or bare) JSON object out of the agent's text."""
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    blob = m.group(1) if m else None
    if blob is None:
        m = re.search(r"(\{.*\})", text, re.DOTALL)  # bare object fallback
        blob = m.group(1) if m else None
    if blob is None:
        return None
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        return None


def _coerce_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _coerce_bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "passed", "pass", "1", "green")
    return bool(value)


def _as_list(value) -> list:
    """Normalize a value to a list of non-empty strings (agent may return a str)."""
    if value is None:
        return []
    items = [value] if isinstance(value, str) else list(value)
    return [str(i).strip() for i in items if str(i).strip()]


def _incident_log(incident: dict) -> str:
    """The raw log/stack-trace excerpt from the detected incident (for the ticket)."""
    return incident.get("traceback_text") or incident.get("traceback") or ""


def _parse_diagnosis(text: str) -> dict | None:
    """Extract and normalize the JSON diagnosis from the agent's final text."""
    data = _extract_json(text)
    if data is None:
        return None
    return {
        "root_cause": data.get("root_cause", ""),
        "steps_to_reproduce": _as_list(data.get("steps_to_reproduce")),
        "files_changed": data.get("files_changed", []),
        "fix_description": data.get("fix_description", ""),
        "test_added": data.get("test_added", ""),
        "acceptance_criteria": _as_list(data.get("acceptance_criteria")),
        "confidence": _coerce_int(data.get("confidence")),
    }


def _parse_fix_result(text: str) -> dict | None:
    """Like _parse_diagnosis, plus the P5 fix fields (test_added file + pass/fail)."""
    base = _parse_diagnosis(text)
    if base is None:
        return None
    data = _extract_json(text) or {}
    base["test_passed"] = _coerce_bool(data.get("test_passed"))
    return base


def _fallback(incident: dict) -> dict:
    """Deterministic diagnosis used when the SDK is unavailable or returns no JSON."""
    return {
        "root_cause": (
            f"{incident.get('exception_class', 'Exception')} at "
            f"{incident.get('file')}:{incident.get('line')} — the enrollment lookup for "
            f"student {incident.get('student_id')} in {incident.get('academic_year')} "
            "returned null and was dereferenced without a null check."
        ),
        "steps_to_reproduce": [
            "Open the student progress dashboard (or call the report endpoint directly).",
            f"Request a report for student {incident.get('student_id')} in academic year "
            f"{incident.get('academic_year')} (a year the student is not enrolled in).",
            "Observe the request fail with an unhandled server error / the logged exception.",
        ],
        "files_changed": [
            "src/main/java/com/example/studentprogress/service/StudentReportService.java"
        ],
        "fix_description": (
            "Null-check the enrollment lookup and return HTTP 404 with a structured "
            "error body when no enrollment exists for the requested year."
        ),
        "test_added": "generateReport_returns404_whenStudentNotEnrolledInYear",
        "log_excerpt": _incident_log(incident),
        "acceptance_criteria": [
            "Requesting a report for a year the student is not enrolled in returns HTTP 404 "
            "with a structured error body (not a 500 / unhandled exception).",
            "A regression test reproduces the scenario and passes.",
            "Existing tests remain green.",
        ],
        "confidence": 2,
        "source": "fallback",
    }


async def _diagnose_async(incident: dict) -> dict | None:
    from claude_agent_sdk import (
        query,
        ClaudeAgentOptions,
        AssistantMessage,
        TextBlock,
    )

    options = ClaudeAgentOptions(
        model=config.claude_model,
        cwd=str(BACKEND_DIR),
        allowed_tools=["Read", "Grep", "Glob"],
        permission_mode="bypassPermissions",  # read-only tools; never prompt (headless)
        system_prompt=SYSTEM_PROMPT,
        max_turns=12,
    )

    console.print("\n[bold cyan]🤖 Diagnosing with Claude Agent SDK (read-only)…[/bold cyan]")
    console.rule(style="cyan")
    chunks: list[str] = []
    async for message in query(prompt=_build_prompt(incident), options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    console.print(block.text, end="", style="white")
                    chunks.append(block.text)
    console.print()
    console.rule(style="cyan")
    return _parse_diagnosis("".join(chunks))


def run_agent(incident: dict) -> dict:
    """
    Diagnose the incident and return a structured dict:
    {root_cause, files_changed, fix_description, test_added, confidence}.

    The result carries a "source" key: "agent-sdk" for a live, code-grounded
    diagnosis, or "fallback" for the deterministic local one. Falls back if the
    SDK is unavailable (e.g. not installed, or no credentials in headless CI) or
    the agent returns no parseable JSON.
    """
    try:
        diagnosis = asyncio.run(_diagnose_async(incident))
    except Exception as e:  # noqa: BLE001 — surface clearly, then degrade gracefully
        console.print(f"[yellow]Agent SDK diagnosis unavailable ({e}); using fallback.[/yellow]")
        diagnosis = None
    if not diagnosis or not diagnosis.get("root_cause"):
        return _fallback(incident)
    diagnosis["source"] = "agent-sdk"
    diagnosis.setdefault("log_excerpt", _incident_log(incident))
    return diagnosis


# ─────────────────────────────────────────────────────────────────────────────
# Phase 5 — write the fix + a regression test and run the build.
# ─────────────────────────────────────────────────────────────────────────────

FIX_SYSTEM_PROMPT = (
    "You are an on-call SRE for a K-8 education platform (Spring Boot + Maven + "
    "TestNG + Mockito). You FIX one production exception with the smallest "
    "responsible change, add a regression test that fails before the fix and "
    "passes after, and prove it by running the build. Only touch the offending "
    "file and its test. Never change unrelated code. A human reviews your PR — "
    "do not commit, push, or merge anything yourself."
)

FIX_PROMPT_TEMPLATE = """\
A production exception was detected. Diagnose it, then APPLY the fix in this
repository (cwd is the service root).

INCIDENT
- Exception: {exception_class}
- Message  : {message}
- Location : {file}:{line}
- Request  : {request_params}

Traceback:
{traceback_text}

TASKS (do them, using your Read/Grep/Glob/Edit/Write/Bash tools):
1. Read the offending file and the related controller/service/repository.
2. Apply a MINIMAL fix to the offending file: when the lookup returns null,
   return HTTP 404 with a structured error body instead of dereferencing null.
   Do not change unrelated code.
3. Add a TestNG regression test under src/test/java/... that:
   - mocks the repository with Mockito (do NOT boot the Spring context),
   - reproduces the exact failure scenario,
   - asserts the new 404 / not-found behavior,
   - uses @Test(description = "..."),
   - remember TestNG assertEquals takes (actual, expected) — the OPPOSITE of JUnit.
4. Run `./mvnw test -q` and iterate until it passes.
5. Output ONLY a fenced ```json block with exactly these keys:
{{
  "root_cause": "<one or two sentences; cite file:line>",
  "steps_to_reproduce": ["<step 1>", "<step 2>", "..."],
  "files_changed": ["<relative paths you actually edited/created>"],
  "fix_description": "<what you changed>",
  "test_added": "<the new test method name>",
  "acceptance_criteria": ["<testable condition for done>", "..."],
  "test_passed": <true|false from the ./mvnw test run>,
  "confidence": <integer 1-5>
}}
"""


def _build_fix_prompt(incident: dict) -> str:
    return FIX_PROMPT_TEMPLATE.format(
        exception_class=incident.get("exception_class", ""),
        message=incident.get("message") or incident.get("exception_message") or "",
        file=incident.get("file", ""),
        line=incident.get("line", ""),
        request_params=(
            incident.get("request_params")
            or f"studentId={incident.get('student_id')}, academicYear={incident.get('academic_year')}"
        ),
        traceback_text=incident.get("traceback_text") or incident.get("traceback") or "",
    )


async def _fix_async(incident: dict) -> dict | None:
    from claude_agent_sdk import (
        query,
        ClaudeAgentOptions,
        AssistantMessage,
        TextBlock,
    )

    options = ClaudeAgentOptions(
        model=config.claude_model,
        cwd=str(BACKEND_DIR),
        # Read to understand, Edit/Write to fix, Bash to run the build.
        allowed_tools=["Read", "Grep", "Glob", "Edit", "Write", "Bash"],
        # Hackathon scope: tools are confined to the service root (cwd). The
        # agent never commits/pushes — github_client opens the PR for review.
        # Before using AutoFix on a real repo, tighten this (e.g. an allow-listed
        # Bash command set and a sandboxed working copy).
        permission_mode="bypassPermissions",
        system_prompt=FIX_SYSTEM_PROMPT,
        max_turns=60,
    )

    console.print("\n[bold magenta]🛠️  Writing fix + regression test with the Claude Agent SDK…[/bold magenta]")
    console.rule(style="magenta")
    chunks: list[str] = []
    async for message in query(prompt=_build_fix_prompt(incident), options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    console.print(block.text, end="", style="white")
                    chunks.append(block.text)
    console.print()
    console.rule(style="magenta")
    return _parse_fix_result("".join(chunks))


def run_fix(incident: dict) -> dict:
    """
    Phase 5: have the agent apply the fix, add a regression test, and run the
    build. Returns the diagnosis dict plus:
      - "test_passed": bool — did ./mvnw test go green
      - "fix_applied": bool — did the agent actually edit code
      - "source": "agent-sdk" | "fallback"

    Degrades to a diagnosis-only fallback (fix_applied=False) when the SDK is
    unavailable, so the pipeline still produces a ticket/PR for a human.
    """
    try:
        result = asyncio.run(_fix_async(incident))
    except Exception as e:  # noqa: BLE001 — surface clearly, then degrade gracefully
        console.print(f"[yellow]Agent SDK fix unavailable ({e}); no code change written.[/yellow]")
        result = None
    if not result or not result.get("root_cause"):
        fb = _fallback(incident)
        fb["test_passed"] = False
        fb["fix_applied"] = False
        return fb
    result["source"] = "agent-sdk"
    result["fix_applied"] = True
    result.setdefault("log_excerpt", _incident_log(incident))
    return result
