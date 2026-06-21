# AutoFix Agent (`autopilot/`)

This directory **is** AutoFix — the Python incident-response agent. It watches a
log file, detects exceptions the moment they occur, parses them into structured
incidents, asks Claude to diagnose the root cause against the real source tree,
then files a Jira ticket and opens a draft GitHub PR.

```
app.log  →  log_watcher  →  log_reader  →  claude_agent      →  jira_client + github_client
(crash)     (tails file)    (parses)       (diagnose w/ SDK)     (ticket + draft PR)
                                  └────────────────────────── autopilot.py orchestrates ──┘
```

> New here? Start with the repo-root [`README.md`](../README.md) for the big
> picture and onboarding-your-own-service guide. This file is the detailed
> run/test reference.

---

## Setup

```bash
cd autopilot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

`requirements.txt` includes **`claude-agent-sdk`** — this is what powers the
live diagnosis. Without it, AutoFix still runs but degrades to a canned fallback
diagnosis (and says so).

---

## Connecting to Claude

Pick one in `.env` (no code change needed):

- **Keyless** — signed into the `claude` CLI locally → leave `ANTHROPIC_API_KEY`
  and `CLAUDE_BASE_URL` blank; the Agent SDK reuses your login.
- **API key** — set `ANTHROPIC_API_KEY` (best for CI/headless).
- **Gateway / Bedrock** — set `CLAUDE_BASE_URL` (+ token) or the standard
  Bedrock/Vertex env vars.

Default model: `claude-sonnet-4-6` (override with `CLAUDE_MODEL`).

---

## Running

### Live watch (the day-to-day mode)
```bash
python log_watcher.py --watch
```
Tails the log; prints a detection panel + live diagnosis on each new exception.

### One-shot full pipeline (detect → diagnose → ticket → PR)
```bash
python autopilot.py
```
Reads the latest exception from the log and runs the whole flow. With no
Jira/GitHub creds it uses a **mock ticket + mock PR** (demo mode). The summary
reports the **diagnosis source**: `live Agent SDK` vs a `⚠ fallback` warning.

---

## File Overview

| File | Responsibility |
|---|---|
| `config.py` | Central config; loads `.env`; resolves Claude auth, model, log path |
| `log_reader.py` | Parses log ERROR blocks into a structured `Incident` *(stack-specific regex)* |
| `log_watcher.py` | Tails the log file; fires on each new exception |
| `detector.py` | Plain-English diagnosis summary (Claude streaming or local fallback) |
| `claude_agent.py` | Grounded diagnosis via the Claude Agent SDK; tags result `source` *(stack-specific prompt)* |
| `autopilot.py` | Orchestrator: detect → diagnose → Jira → draft PR |
| `jira_client.py` | Creates a Jira bug via the Cloud REST API |
| `github_client.py` | Commits a fix branch and opens a draft PR |
| `tests/` | pytest suite (SDK mocked; one opt-in live integration test) |

---

## Testing / Verification

All from `autopilot/` with the venv active.

| Check | Command | Expect |
|---|---|---|
| Config resolves | `python config.py` | `Config OK.` and `Log exists : True` |
| Parser extracts data | `python log_reader.py` | JSON with `student_id`, `file`, `line`, `exception_class` |
| Detector summary | `python detector.py` | A 2–3 sentence summary of the latest incident |
| Unit/wiring suite | `python -m pytest` | all pass (Claude SDK mocked) |
| **Live diagnosis** | `python -m pytest -m integration -s tests/test_claude_agent.py` | a real Claude diagnosis (needs Claude access) |

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Log file not found` | Start the service first; confirm it created the log at `LOG_PATH` |
| Diagnosis shows `⚠ fallback` | `claude-agent-sdk` not installed, or no Claude credentials — see *Connecting to Claude* |
| `Claude call failed` / SDK error | Check your auth (login / `ANTHROPIC_API_KEY` / `CLAUDE_BASE_URL`); AutoFix degrades gracefully |
| `ModuleNotFoundError` | Activate the venv and re-run `pip install -r requirements.txt` |
| Watcher prints nothing on a crash | Make sure you triggered a real, unhandled exception that reached the log |

