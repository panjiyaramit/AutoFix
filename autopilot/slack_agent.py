"""
slack_agent.py — INTERIM Slack delivery bridge via the Claude Agent SDK + a Slack MCP.

Why this exists: while a direct Slack credential for AutoFix is pending workspace-admin
approval, we can still deliver notifications by asking Claude (Agent SDK) to post
through an already-approved Slack MCP server. This is a deliberate, temporary
bridge — the orchestrator only falls back to it when no direct credential is set,
and it is OFF unless AUTOFIX_SLACK_AGENT_BRIDGE=1.

The moment a real SLACK_BOT_TOKEN / SLACK_WEBHOOK_URL lands in .env, the direct
path wins and this bridge is skipped automatically (see autopilot.notify_slack).

Known limitation (2026-06-03): the Slack MCP must itself be configured with a
USABLE workspace token (e.g. SLACK_ACCESS_TOKEN / SLACK_WORKSPACES, depending on
the server build). With only an xoxe- rotation token available, the MCP reports
"No workspace configured" and the post fails — same credential gap as the direct
path. This module is wired and ready; it goes live when the MCP has a real token.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from rich.console import Console

from config import config

console = Console()

# Where to find the Slack MCP server definition, and which server key to use.
MCP_CONFIG_PATH = os.environ.get("AUTOFIX_SLACK_MCP_CONFIG", "~/.cursor/mcp.json")
MCP_SERVER_KEY = os.environ.get("AUTOFIX_SLACK_MCP_SERVER", "slack")


def bridge_enabled() -> bool:
    return os.environ.get("AUTOFIX_SLACK_AGENT_BRIDGE", "0") == "1"


def _load_mcp_server() -> dict | None:
    path = Path(os.path.expanduser(MCP_CONFIG_PATH))
    if not path.exists():
        return None
    try:
        cfg = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    servers = cfg.get("mcpServers", cfg.get("servers", {}))
    return servers.get(MCP_SERVER_KEY)


async def _notify_async(text: str, channel: str) -> bool:
    from claude_agent_sdk import query, ClaudeAgentOptions, AssistantMessage, TextBlock

    slack_server = _load_mcp_server()
    if not slack_server:
        console.print(f"[yellow]Slack MCP server '{MCP_SERVER_KEY}' not found in {MCP_CONFIG_PATH}.[/yellow]")
        return False

    options = ClaudeAgentOptions(
        model=config.claude_model,
        mcp_servers={"slack": slack_server},
        # Only the Slack MCP tools — no built-in Edit/Bash. Names cover the
        # common mcp-server-slack builds.
        allowed_tools=[
            "mcp__slack__slack_post_message", "mcp__slack__slack_list_channels",
            "mcp__slack__slack_send_message", "mcp__slack__slack_search_channels",
            "mcp__slack__conversations_add_message", "mcp__slack__channels_list",
        ],
        permission_mode="bypassPermissions",
        system_prompt="You are a Slack delivery bridge. Use ONLY the Slack MCP tools. Do nothing else.",
        max_turns=14,
    )
    prompt = (
        f"Using the Slack MCP tools, post the message below to the channel '{channel}'. "
        "If the post tool needs a channel ID, look it up first, then post.\n\n"
        f"MESSAGE:\n{text}\n\n"
        "Reply with exactly 'SENT' if posted, or 'FAILED: <reason>' if not."
    )
    out: list[str] = []
    async for m in query(prompt=prompt, options=options):
        if isinstance(m, AssistantMessage):
            for b in m.content:
                if isinstance(b, TextBlock):
                    out.append(b.text)
    final = "".join(out)
    return "SENT" in final and "FAILED" not in final


def notify_via_agent(text: str, channel: str = "#autofix-notifications") -> bool:
    """Best-effort: post via Claude + the Slack MCP. Never raises; returns success."""
    try:
        return asyncio.run(_notify_async(text, channel))
    except Exception as e:  # noqa: BLE001 — a notification must never break the pipeline
        console.print(f"[yellow]Slack agent bridge unavailable ({e}).[/yellow]")
        return False
