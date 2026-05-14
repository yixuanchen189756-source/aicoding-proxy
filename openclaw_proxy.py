#!/usr/bin/env python3
"""Run the OpenClaw proxy."""

from __future__ import annotations

import os
from pathlib import Path


os.environ.setdefault("OPENAI_PROXY_CONFIG", str(Path(__file__).with_name("config.yaml")))

from openclaw_client import main  # noqa: E402


if __name__ == "__main__":
    main()
