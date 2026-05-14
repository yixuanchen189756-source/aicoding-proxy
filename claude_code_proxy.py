#!/usr/bin/env python3
"""Run the Claude Code proxy profile."""

from __future__ import annotations

import os
from pathlib import Path

from agent_proxy_core import main_profile


if __name__ == "__main__":
    os.environ.setdefault("OPENAI_PROXY_CONFIG", str(Path(__file__).with_name("config.yaml")))
    main_profile("claude-code")
