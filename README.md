# AutoFix — the Self-Healing Agent

**AutoFix is an autonomous incident-response agent.** It watches your service's
logs, and the moment an unhandled exception appears it asks Claude to read your
actual source code, diagnose the root cause, file a Jira ticket, and open a
draft GitHub PR — so a human gets a grounded explanation and a starting point
instead of a raw stack trace at 2 a.m.

AutoFix follows **Detect → Diagnose → Fix → Deliver** — it reads your code, writes
the fix *and* a regression test, proves it with the build, then opens a draft PR
for a human to approve (see [Status](#status)).

```
┌──────────────────────┐  exception   ┌──────────────────────┐  diagnosis   ┌──────────────────┐
│  YOUR SERVICE        │  written to  │  AutoFix(this repo)  │  +  draft    │  Jira ticket     │
│  (any app that logs  │  ─────────▶  │  watch → parse →     │  ─────────▶  │  GitHub draft PR │
│   to a file)         │   app.log    │  diagnose w/ Claude  │              │  (human reviews) │
└──────────────────────┘              └──────────────────────┘              └──────────────────┘
```

AutoFix never merges anything on its own. Every result lands as a **draft PR for
human review**.

---

## Contents

- [The 7 Stages](#the-7-stages)
- [Status](#status)
- [Will this work for my team's service?](#will-this-work-for-my-teams-service)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start-5-minutes-using-the-bundled-demo)
- [Onboarding YOUR service](#onboarding-your-service)
- [Connecting to Claude](#connecting-to-claude)
- [Repository Layout](#repository-layout)
- [Testing](#testing)
- [Credentials & secrets](#credentials--secrets-each-user-brings-their-own)
- [Safety & responsible use](#safety--responsible-use)

---

## The 7 Stages

![AutoFix — the 7-stage self-healing flow](autofix-flow.png)

AutoFix runs every incident through the same seven stages:

| # | Stage | What happens |
|---|-------|--------------|
| 1 | **Detect** | Tail the log in real time; parse the stack trace into a structured incident (exception, file:line, request params). |
| 2 | **Log Jira** | Open a Jira ticket immediately — "diagnosis in progress…". |
| 3 | **Notify** | Post to Slack: incident detected, ticket created, working on a fix. |
| 4 | **Fix** | Claude reads the real source, finds the root cause, writes the fix **and** a regression test, and runs the build to verify it. |
| 5 | **Open PR** | Push a branch and open a **draft** pull request with the fix. |
| 6 | **Update Jira** | Enrich the ticket with the root cause, the fix, and the PR link. |
| 7 | **Notify** | Post the final Slack summary: fix written, tests green, PR ready for review. |

> Stages 1–3 and 5–7 are deterministic plumbing. Stage 4 is the intelligent core — an autonomous **Claude Agent SDK** loop. A human always reviews and merges the PR; AutoFix never auto-merges.

---

## Status

| Capability | State |
|---|---|
| **Detect** — real-time log watching + exception parsing | ✅ Working |
| **Diagnose** — Claude reads your code (Agent SDK) and explains the root cause | ✅ Working |
| **Fix** — Claude edits the code, writes a regression test, runs `./mvnw test` | ✅ Working (verified end-to-end) |
| **Deliver** — Jira ticket + draft GitHub PR + Slack notification | ✅ Working (mock/skip fallback without creds) |

AutoFix detects an exception, has the agent write the fix **and** a passing
regression test (proven by running the build), then files a ticket, opens a
**draft** PR, and pings Slack. A human reviews and approves — nothing
auto-merges. Jira/GitHub/Slack run in mock/skip mode until you provide
credentials.

> **Slack live delivery (P8) — working.** Verified end-to-end against a real
> incoming webhook (`#AutoFix-notifications`). Delivery uses a fallback chain:
> **(1) direct** (`SLACK_BOT_TOKEN`/`SLACK_WEBHOOK_URL` in `.env`) →
> **(2) interim agent bridge** (Claude Agent SDK posts via an already-approved
> Slack MCP, opt-in with `AutoFix_SLACK_AGENT_BRIDGE=1`) → **(3) demo** (sends
> nothing). Set your own `SLACK_WEBHOOK_URL` (or `xoxb-` bot token) in
> `autopilot/.env` — each user brings their own; the webhook is never committed.

---

## Will this work for my team's service?

| Your stack | Out of the box? |
|---|---|
| **JVM / Spring Boot + Maven** (logs `yyyy-MM-dd HH:mm:ss LEVEL logger - msg`) | ✅ Yes |
| Anything else (Node, Python, Go, …) | ⚙️ Adapt two things (below) — the architecture is stack-agnostic, the parser and prompt are not |

The detection and diagnosis engine doesn't care what language you use, but two
pieces are currently tuned for Spring Boot. To onboard a different stack you
adjust:

1. **`autopilot/log_reader.py`** — the regexes that recognise a log header and a
   stack frame. Point them at your log format.
2. **`autopilot/claude_agent.py`** — the system prompt mentions Spring
   Boot/Maven/TestNG. Describe your stack instead.

Everything else (watcher, orchestrator, Jira, GitHub, Claude connection) is
reusable as-is.

---

## Prerequisites

| Tool | Version | Needed for |
|---|---|---|
| Python | 3.11+ | The AutoFix agent (`autopilot/`) |
| The Claude Code CLI **or** an Anthropic API key **or** a gateway | — | Talking to Claude (see [Connecting to Claude](#connecting-to-claude)) |
| Java 17+ & Maven | only for the bundled demo backend | Trying AutoFix end-to-end before pointing it at your own service |
| git | any | Version control + the GitHub PR step |

---

## Quick Start (5 minutes, using the bundled demo)

The repo ships a deliberately-buggy demo service so you can watch AutoFix work
before wiring it into your own system.

### 1. Start the agent

```bash
cd autopilot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # defaults are fine for a local keyless run
python log_watcher.py --watch
```

You'll see the blue **"AutoFix — Log Watcher"** panel. Leave it running.

### 2. Trigger an incident (separate terminal)

```bash
cd backend
mvn spring-boot:run           # demo service on http://localhost:8000
# then cause the seeded crash:
curl "http://localhost:8000/api/students/4271/report?academicYear=2023-24"
```

Within ~2 seconds the watcher prints a 🔴 **Exception Detected** panel followed
by a live, code-grounded diagnosis from Claude.

### 3. Run the full pipeline (detect → diagnose → ticket → PR)

```bash
cd autopilot && source .venv/bin/activate
python autopilot.py
```

With no Jira/GitHub credentials it runs in **demo mode** (mock ticket + mock PR)
so you can see the whole flow safely. Add credentials in `.env` to create real
ones.

> Tip: the final summary prints the **diagnosis source** — `live Agent SDK` means
> Claude really read your code; a `⚠ fallback` warning means it couldn't reach
> Claude and used a canned answer (see [Connecting to Claude](#connecting-to-claude)).

---

## Onboarding YOUR service

1. **Point AutoFix at your log and your code** in `autopilot/.env`:
   ```ini
   LOG_PATH=/path/to/your/service/app.log
   TARGET_REPO_DIR=/path/to/your/service/repo
   ```
2. **Adapt the parser and prompt** if you're not on Spring Boot (see
   [Will this work for my team?](#will-this-work-for-my-teams-service)).
3. **Connect to Claude** (next section).
4. Run `python log_watcher.py --watch` (live) or `python autopilot.py`
   (one-shot, full pipeline) — ideally as a small always-on service next to your
   app, or as a CI step.

---

## Connecting to Claude

AutoFix uses the **Claude Agent SDK** for diagnosis. Pick whichever auth fits — no
code changes needed:

| Option | When | How |
|---|---|---|
| **Keyless (Claude Code login)** | Local dev, on a machine where you're signed into the `claude` CLI | Leave `ANTHROPIC_API_KEY` and `CLAUDE_BASE_URL` blank — the SDK reuses your login |
| **API key** | CI / headless / servers | Set `ANTHROPIC_API_KEY` (request one via your IT helpdesk if your org manages Claude) |
| **Corporate gateway / Bedrock** | Enterprise networks | Set `CLAUDE_BASE_URL` (+ token), or the standard Bedrock/Vertex env vars |

> **Headless/CI note:** the keyless login lives in your user environment, so it
> does **not** exist on a build agent. For unattended runs (e.g. the Jenkins
> stage), provide an API key or gateway — otherwise AutoFix degrades to its
> fallback diagnosis and prints a ⚠ warning.

The default model is **`claude-sonnet-4-6`** (override with `CLAUDE_MODEL`).

---

## Repository Layout

```
AutoFix-self-healing-pipeline/
├── autopilot/                      The AutoFix agent (Python) — this is the product
│   ├── config.py                   central config (Claude auth, paths, model)
│   ├── log_reader.py               parses log exceptions → structured incident   ⚙️ stack-specific
│   ├── log_watcher.py              real-time log tailer
│   ├── detector.py                 plain-English diagnosis summary
│   ├── claude_agent.py             grounded diagnosis via the Claude Agent SDK    ⚙️ stack-specific prompt
│   ├── jira_client.py              creates a Jira bug
│   ├── github_client.py            opens a draft PR
│   ├── autopilot.py                orchestrator: detect → diagnose → ticket → PR
│   ├── tests/                      pytest suite (SDK mocked; live test opt-in)
│   ├── requirements.txt
│   └── .env.example
│
├── backend/                        Bundled demo service (Spring Boot) for trying AutoFix
├── Jenkinsfile                     CI pipeline (build/test demo + AutoFix incident check)
├── reset.sh                        demo cleanup script
└── README.md
```

---

## Testing

```bash
cd autopilot && source .venv/bin/activate
python -m pytest                 # fast unit/wiring tests (Claude SDK mocked)
python -m pytest -m integration -s tests/test_claude_agent.py   # live SDK call (opt-in)
```

---

## Credentials & secrets (each user brings their own)

AutoFix ships **no** tokens. Every integration credential is personal and stays on
your machine:

- Copy the template and fill in your own values:
  ```bash
  cp autopilot/.env.example autopilot/.env   # then edit autopilot/.env
  ```
- **`autopilot/.env` is gitignored — never commit it.** Only `.env.example`
  (blank placeholders) is tracked. Don't paste real tokens into any tracked file.
- Each teammate generates and uses their **own** Jira / GitHub / Slack tokens.
  Tokens are scoped to the person who creates them, so a token committed by one
  person would both leak a secret and act as the wrong identity.

### Getting a Slack credential (for `#AutoFix-notifications`)

> Heads-up: in a managed workspace (e.g. Curriculum Associates), creating a
> Slack app may need admin approval — if so, file an IT Helpdesk request first.

**Option A — Incoming webhook (simplest, one channel):**
1. Go to <https://api.slack.com/apps> → **Create New App → From scratch**; name it
   `AutoFix`, pick your workspace.
2. **Features → Incoming Webhooks → toggle On**.
3. **Add New Webhook to Workspace** → choose **#AutoFix-notifications** → **Allow**.
4. Copy the URL (`https://hooks.slack.com/services/T…/B…/…`) into `autopilot/.env`:
   ```ini
   SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T…/B…/…
   ```
   (The webhook is bound to that channel; `SLACK_CHANNEL` is ignored in this mode.)

**Option B — Bot token (targets a named channel, more flexible):**
1. Same app → **OAuth & Permissions → Scopes → Bot Token Scopes → add `chat:write`**.
2. **Install to Workspace**, then copy the **Bot User OAuth Token** (`xoxb-…`).
3. In Slack, invite the bot to the channel: `/invite @AutoFix` in **#AutoFix-notifications**.
4. In `autopilot/.env`:
   ```ini
   SLACK_BOT_TOKEN=xoxb-…
   SLACK_CHANNEL=#AutoFix-notifications
   ```

Either way, run `python autopilot.py` — on a real incident the summary posts to
`#AutoFix-notifications`. With neither set, Slack stays in demo mode (sends nothing).

The same "bring your own token" pattern applies to **Jira** (`JIRA_TOKEN`, from
<https://id.atlassian.com/manage-profile/security/api-tokens>) and **GitHub**
(`GITHUB_TOKEN`, a personal access token with repo scope).

---

## Safety & responsible use

- **Human-in-the-loop:** AutoFix opens *draft* PRs and never auto-merges.
- **Synthetic data only:** the demo uses fake student names/IDs/scores — no real
  PII. Keep real PII out of logs you point AutoFix at, since log contents are sent
  to Claude for diagnosis.
- **Review like any AI-assisted change:** anything AutoFix proposes goes through
  your normal code review, CI, and security scanning before merge.
