#!/usr/bin/env python3
"""Run the Hermes proxy profile."""

from __future__ import annotations

import os
from pathlib import Path

from client import main_profile


if __name__ == "__main__":
    os.environ.setdefault("OPENAI_PROXY_CONFIG", str(Path(__file__).with_name("config.yaml")))
    main_profile("hermes")
