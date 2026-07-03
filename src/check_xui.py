#!/usr/bin/env python3
"""Diagnostic script to verify 3x-ui API connectivity and Reality settings."""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from functions import XUIAPI
from config import config


async def main():
    api = XUIAPI()
    try:
        print("=== 3x-ui API Diagnostic ===\n")

        # Login (auto-detects CSRF and base-path)
        ok = await api.login()
        print(f"login={ok}")
        if not ok:
            print("ERROR: Cannot login. Check XUI_API_URL, XUI_USERNAME, XUI_PASSWORD.")
            return

        # Show detected settings
        print(f"csrf_token={'present' if api._csrf_token else 'none (old 3x-ui)'}")
        print(f"base_path={api._base_path or '/'}")

        # Get inbound
        inbound = await api.get_inbound(config.INBOUND_ID)
        print(f"inbound_exists={bool(inbound)}")

        if inbound:
            print(f"  id={inbound.get('id')}")
            print(f"  remark={inbound.get('remark')}")
            print(f"  port={inbound.get('port')}")
            print(f"  protocol={inbound.get('protocol')}")
            print(f"  enable={inbound.get('enable')}")

            # Client count
            settings = api._loads_json(inbound.get("settings", "{}"), {})
            clients = settings.get("clients", [])
            print(f"  clients={len(clients)}")

        # Reality settings
        reality = await api.get_reality_settings()
        print(f"\nreality_loaded={bool(reality)}")

        if reality:
            safe = dict(reality)
            # Mask sensitive values
            if safe.get("public_key"):
                safe["public_key"] = safe["public_key"][:8] + "***"
            if safe.get("short_id"):
                safe["short_id"] = safe["short_id"][:4] + "***"
            for k, v in safe.items():
                print(f"  {k}={v}")
        else:
            print("  WARNING: Reality settings could not be parsed.")
            print("  Check INBOUND_ID and that the inbound has Reality configured.")

        # Subscription URL test
        sub_path = (config.XUI_SUB_PATH or "/sub/").strip()
        print(f"\nsubscription_path={sub_path}")
        print(f"subscription_base={config.SUBSCRIPTION_URL_BASE or '(auto)'}")

    finally:
        await api.close()


if __name__ == "__main__":
    asyncio.run(main())
