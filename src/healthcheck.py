#!/usr/bin/env python3
"""Container healthcheck for the Telegram bot application."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REQUIRED_ENV_VARS = ("BOT_TOKEN", "XUI_API_URL", "INBOUND_ID")
XUI_TIMEOUT_SECONDS = float(os.getenv("HEALTHCHECK_XUI_TIMEOUT", "2"))
SKIP_XUI_CHECK = os.getenv("HEALTHCHECK_SKIP_XUI", "false").lower() in {"1", "true", "yes"}


def fail(message: str) -> int:
    print(f"unhealthy: {message}", file=sys.stderr)
    return 1


def required_environment_is_valid() -> tuple[bool, str]:
    missing = [name for name in REQUIRED_ENV_VARS if not os.getenv(name)]
    if missing:
        return False, f"missing required environment variables: {', '.join(missing)}"

    try:
        inbound_id = int(os.environ["INBOUND_ID"])
    except ValueError:
        return False, "INBOUND_ID must be an integer"

    if inbound_id <= 0:
        return False, "INBOUND_ID must be a positive integer"

    return True, ""


def app_process_is_running() -> bool:
    """Return True when the container's main app.py process is present."""
    proc = Path("/proc")
    if not proc.exists():
        return True

    current_pid = os.getpid()
    for entry in proc.iterdir():
        if not entry.name.isdigit() or int(entry.name) == current_pid:
            continue

        try:
            cmdline = (entry / "cmdline").read_bytes().replace(b"\x00", b" ").decode(errors="ignore")
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue

        if "python" in cmdline and "app.py" in cmdline:
            return True

    return False


def xui_is_reachable() -> tuple[bool, str]:
    if SKIP_XUI_CHECK:
        return True, ""

    request = Request(os.environ["XUI_API_URL"], method="GET", headers={"User-Agent": "frostbite-healthcheck/1.0"})
    try:
        with urlopen(request, timeout=XUI_TIMEOUT_SECONDS) as response:
            if response.status < 500:
                return True, ""
            return False, f"3x-ui returned HTTP {response.status}"
    except HTTPError as exc:
        if exc.code < 500:
            return True, ""
        return False, f"3x-ui returned HTTP {exc.code}"
    except (TimeoutError, URLError, OSError) as exc:
        return False, f"3x-ui is not reachable: {exc}"


def main() -> int:
    env_ok, env_error = required_environment_is_valid()
    if not env_ok:
        return fail(env_error)

    if not app_process_is_running():
        return fail("app.py process is not running")

    xui_ok, xui_error = xui_is_reachable()
    if not xui_ok:
        return fail(xui_error)

    print("healthy")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
