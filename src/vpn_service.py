"""VPN Profile service layer — single source of truth for profile operations.

All 3x-ui API calls and database writes go through this service.
Telegram handlers should NOT call 3x-ui API or modify DB directly.
"""

import json
import logging
from datetime import datetime, timedelta

from config import config
from database import (
    Session, User, VPNProfile, get_active_profile, save_profile, save_user,
    validate_and_fix_subscription_date,
)
from functions import XUIAPI, build_bot_profile_name
from urllib.parse import quote

logger = logging.getLogger(__name__)


class VPNService:
    """Manages VPN profiles: creation, verification, renewal, sync."""

    def __init__(self):
        self._api = XUIAPI()

    async def close(self):
        await self._api.close()

    # ─── Register ────────────────────────────────────────────────────────

    async def register_vpn_profile(self, user: User) -> VPNProfile | None:
        """Create a VPN profile: generate client → add to 3x-ui → save to DB."""
        import uuid as _uuid

        email = build_bot_profile_name(user.telegram_id, user.username)
        sub_id = str(_uuid.uuid5(_uuid.NAMESPACE_DNS, f"user_{user.telegram_id}"))
        client_id = str(_uuid.uuid4())
        comment = f"FS{user.telegram_id}"
        inbound_ids = config.INBOUND_IDS if config.INBOUND_IDS else [config.INBOUND_ID]

        # Calculate expiry
        now = datetime.utcnow()
        if user.subscription_end and user.subscription_end > now:
            expiry_time = int(user.subscription_end.timestamp())
        else:
            expiry_time = 0  # unlimited

        # Create profile record with status=creating
        profile = VPNProfile(
            user_id=user.id,
            name=user.full_name or f"Profile {user.telegram_id}",
            xui_client_id=client_id,
            xui_email=email,
            xui_sub_id=sub_id,
            xui_inbound_ids=json.dumps(inbound_ids),
            status='creating',
            subscription_end=user.subscription_end,
        )

        try:
            # Get Reality settings
            reality = await self._api.get_reality_settings()
            if not reality:
                logger.error("Cannot register profile: Reality settings not available")
                profile.status = 'failed'
                save_profile(profile)
                return None

            # Build client data
            new_client = {
                "id": client_id,
                "flow": reality.get("flow", "xtls-rprx-vision"),
                "email": email,
                "limitIp": 3,
                "totalGB": 0,
                "expiryTime": expiry_time * 1000 if expiry_time > 0 else 0,
                "enable": True,
                "tgId": user.telegram_id,
                "subId": sub_id,
                "reset": 0,
                "comment": comment,
            }

            if config.BOT_DRY_RUN:
                logger.info(f"DRY RUN: would create client {email} in inbounds {inbound_ids}")
                profile.status = 'active'
                save_profile(profile)
                return profile

            # Create client in 3x-ui
            success = await self._api.add_client(email, inbound_ids, new_client)
            if not success:
                logger.error(f"Failed to create client {email} via API")
                profile.status = 'failed'
                save_profile(profile)
                return None

            # Verify client exists
            verified = await self._api.get_client(email)
            if not verified:
                logger.error(f"Client {email} not found after creation")
                profile.status = 'failed'
                save_profile(profile)
                return None

            # Add to group
            if config.BOT_GROUP_NAME:
                try:
                    await self._api.add_to_group([email], config.BOT_GROUP_NAME)
                except Exception as e:
                    logger.warning(f"Failed to add to group: {e}")

            profile.status = 'active'
            save_profile(profile)
            logger.info(f"Profile registered: {email} in inbounds {inbound_ids}")
            return profile

        except Exception as e:
            logger.exception(f"Profile registration failed: {e}")
            profile.status = 'failed'
            save_profile(profile)
            return None

    # ─── Verify ─────────────────────────────────────────────────────────

    async def verify_vpn_profile(self, profile: VPNProfile) -> bool:
        """Check if client still exists in 3x-ui."""
        if not profile.xui_email:
            return False
        client = await self._api.get_client(profile.xui_email)
        return client is not None

    # ─── Renew ──────────────────────────────────────────────────────────

    async def renew_vpn_profile(self, profile: VPNProfile, days: int) -> bool:
        """Extend subscription: update 3x-ui → verify → update DB."""
        if not profile.xui_email:
            logger.error("Cannot renew: no xui_email in profile")
            return False

        try:
            # Get current client
            client = await self._api.get_client(profile.xui_email)
            if not client:
                logger.error(f"Client {profile.xui_email} not found for renewal")
                return False

            # Calculate new expiry
            now = datetime.utcnow()
            current_end = profile.subscription_end or now
            if current_end > now:
                new_end = current_end + timedelta(days=days)
            else:
                new_end = now + timedelta(days=days)

            new_end_ms = int(new_end.timestamp() * 1000)

            if config.BOT_DRY_RUN:
                logger.info(f"DRY RUN: would renew {profile.xui_email} by {days} days → {new_end}")
                profile.subscription_end = new_end
                save_profile(profile)
                return True

            # Update in 3x-ui — send only fields that need changing + email
            # Full object replacement causes type mismatches (allowedIPs etc)
            success = await self._api.update_client(profile.xui_email, {
                "email": profile.xui_email,
                "expiryTime": new_end_ms,
                "enable": True,
            })
            if not success:
                logger.error(f"Failed to update expiry for {profile.xui_email}")
                return False

            # Verify
            verified = await self._api.get_client(profile.xui_email)
            if not verified:
                logger.error(f"Client {profile.xui_email} not found after renewal update")
                return False

            verified_expiry = verified.get("expiryTime", 0)
            if verified_expiry < new_end_ms - 1000:
                logger.error(
                    f"Expiry verification failed: expected >={new_end_ms}, got {verified_expiry}"
                )
                return False

            # Update DB
            profile.subscription_end = new_end
            save_profile(profile)
            logger.info(f"Renewed {profile.xui_email} until {new_end}")
            return True

        except Exception as e:
            logger.exception(f"Renewal failed for {profile.xui_email}: {e}")
            return False

    # ─── Sync ───────────────────────────────────────────────────────────

    async def sync_vpn_profile(self, profile: VPNProfile, user: User) -> VPNProfile:
        """Recover profile identifiers by searching 3x-ui."""
        if profile.xui_email:
            client = await self._api.get_client(profile.xui_email)
            if client:
                profile.status = 'active'
                save_profile(profile)
                return profile

        if profile.xui_client_id:
            clients = await self._api.get_online_users()
            # Try to find by other means
            pass

        # Search by tgId comment
        email = build_bot_profile_name(user.telegram_id, user.username)
        client = await self._api.get_client(email)
        if client:
            profile.xui_email = email
            profile.xui_client_id = client.get("id", "")
            profile.xui_sub_id = client.get("subId", "")
            profile.status = 'active'
            save_profile(profile)
            logger.info(f"Synced profile {profile.id} by email {email}")
            return profile

        # Search legacy email format
        legacy_email = f"user_{user.telegram_id}"
        # ... additional search strategies

        profile.status = 'failed'
        save_profile(profile)
        logger.warning(f"Could not sync profile {profile.id}")
        return profile

    # ─── Disable ────────────────────────────────────────────────────────

    async def disable_vpn_profile(self, profile: VPNProfile) -> bool:
        """Disable client in 3x-ui."""
        if not profile.xui_email:
            return False

        success = await self._api.update_client(profile.xui_email, {
            "email": profile.xui_email,
            "enable": False,
        })
        if success:
            profile.status = 'disabled'
            save_profile(profile)
        return success
