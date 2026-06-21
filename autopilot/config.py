"""
Centralized configuration for the AutoFix orchestrator.

Loads environment variables from .env and exposes a frozen Config object.
Fails loudly at import time if anything required is missing or invalid.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Resolve paths relative to this file so the watcher works from any CWD.
AUTOPILOT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = AUTOPILOT_DIR.parent

# Load .env from the autopilot/ directory.
load_dotenv(AUTOPILOT_DIR / ".env")


@dataclass(frozen=True)
class Config:
    anthropic_api_key: str
    claude_model: str
    claude_base_url: str  # empty == talk to Anthropic API directly
    log_path: Path

    @staticmethod
    def load() -> "Config":
        api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        model = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6").strip()
        base_url = os.environ.get("CLAUDE_BASE_URL", "").strip()

        # Resolve LOG_PATH relative to the autopilot dir if it is relative.
        raw_log_path = os.environ.get("LOG_PATH", "../backend/logs/app.log").strip()
        log_path = Path(raw_log_path)
        if not log_path.is_absolute():
            log_path = (AUTOPILOT_DIR / log_path).resolve()

        return Config(
            anthropic_api_key=api_key,
            claude_model=model,
            claude_base_url=base_url,
            log_path=log_path,
        )

    @property
    def uses_proxy(self) -> bool:
        return bool(self.claude_base_url)

    def build_anthropic_client(self):
        """
        Construct an Anthropic client that works with either a direct API key
        or a corporate proxy / LLM gateway (via CLAUDE_BASE_URL).
        Imported lazily so config.py has no hard dependency on the SDK.
        """
        from anthropic import Anthropic

        kwargs = {}
        if self.anthropic_api_key:
            kwargs["api_key"] = self.anthropic_api_key
        if self.claude_base_url:
            kwargs["base_url"] = self.claude_base_url
        return Anthropic(**kwargs)

    def validate(self, require_credentials: bool = False) -> list[str]:
        """Return a list of human-readable problems. Empty list == all good."""
        problems: list[str] = []

        if require_credentials and not self.anthropic_api_key and not self.claude_base_url:
            problems.append(
                "No Claude credentials configured. Set ANTHROPIC_API_KEY for direct "
                "access, or CLAUDE_BASE_URL for a corporate proxy. "
                "Copy .env.example to .env and fill it in."
            )

        if not self.log_path.exists():
            problems.append(
                f"Log file not found at: {self.log_path}\n"
                f"  Start the backend first:  cd backend && mvn spring-boot:run"
            )

        return problems


# Singleton — import this everywhere.
config = Config.load()


def _main() -> None:
    """Smoke test: python config.py"""
    print("AutoFix orchestrator configuration")
    print("-" * 40)
    print(f"  Project root : {PROJECT_ROOT}")
    print(f"  Autopilot dir: {AUTOPILOT_DIR}")
    print(f"  Claude model : {config.claude_model}")
    key_status = "set" if config.anthropic_api_key else "NOT set"
    print(f"  API key      : {key_status}")
    if config.uses_proxy:
        print(f"  Mode         : PROXY ({config.claude_base_url})")
    else:
        print(f"  Mode         : direct Anthropic API")
    print(f"  Log path     : {config.log_path}")
    print(f"  Log exists   : {config.log_path.exists()}")
    print("-" * 40)

    problems = config.validate(require_credentials=False)
    if problems:
        print("\nWarnings:")
        for p in problems:
            print(f"  - {p}")
        sys.exit(1)
    else:
        print("\nConfig OK.")


if __name__ == "__main__":
    _main()
