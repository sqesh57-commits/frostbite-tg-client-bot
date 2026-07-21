from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, ForeignKey, func, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime, timedelta, timezone
import logging
import uuid
import random
import json
import os
from config import config

logger = logging.getLogger(__name__)

Base = declarative_base()

DB_PATH = os.getenv("DB_PATH", "/app/data/users.db")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)


class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True)
    full_name = Column(String)
    username = Column(String)
    registration_date = Column(DateTime, default=datetime.utcnow)
    is_admin = Column(Boolean, default=False)
    subscription_end = Column(DateTime)
    notified = Column(Boolean, default=False)
    notified_3d = Column(Boolean, default=False)
    notified_1d = Column(Boolean, default=False)
    notified_3h = Column(Boolean, default=False)
    vless_profile_id = Column(String)
    vless_profile_data = Column(String)


class VPNProfile(Base):
    __tablename__ = 'vpn_profiles'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    profile_uuid = Column(String, unique=True, default=lambda: str(uuid.uuid4()))
    name = Column(String)
    xui_client_id = Column(String)
    xui_email = Column(String, index=True)
    xui_sub_id = Column(String, index=True)
    xui_inbound_ids = Column(String)
    status = Column(String, default='active', index=True)
    subscription_end = Column(DateTime)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, onupdate=lambda: datetime.now(timezone.utc))
    vless_profile_id = Column(String)
    vless_profile_data = Column(String)


class Order(Base):
    __tablename__ = 'orders'
    id = Column(Integer, primary_key=True)
    order_uuid = Column(String, unique=True, default=lambda: str(uuid.uuid4()), index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    vpn_profile_id = Column(Integer, ForeignKey('vpn_profiles.id'), nullable=True, index=True)
    months = Column(Integer, nullable=False)
    amount = Column(Integer, nullable=False)
    duration_days = Column(Integer)
    tariff_label = Column(String)
    payment_code = Column(String, unique=True, nullable=False, index=True)
    status = Column(String, default='created', index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    paid_at = Column(DateTime)
    verified_at = Column(DateTime)
    verified_by = Column(Integer)


engine = create_engine(f'sqlite:///{DB_PATH}', echo=False)
Session = sessionmaker(bind=engine, expire_on_commit=False)


def to_naive_utc(dt) -> datetime | None:
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt)
        except Exception:
            return None
    if not isinstance(dt, datetime):
        return None
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def validate_and_fix_subscription_date(subscription_end) -> datetime:
    now = datetime.utcnow()
    default = now + timedelta(days=config.TRIAL_DAYS)
    subscription_end = to_naive_utc(subscription_end)
    if subscription_end is None:
        return default
    if subscription_end < datetime(2020, 1, 1) or subscription_end > now + timedelta(days=3650):
        return default
    return subscription_end


def _generate_payment_code() -> str:
    return f"VPN-{random.randint(100000, 999999)}"


def run_migrations():
    with engine.begin() as conn:
        existing_user_cols = {c["name"] for c in inspect(engine).get_columns("users")}
        existing_profile_cols = {c["name"] for c in inspect(engine).get_columns("vpn_profiles")}
        existing_order_cols = {c["name"] for c in inspect(engine).get_columns("orders")}

        user_migrations = {
            "notified_3d": "ALTER TABLE users ADD COLUMN notified_3d BOOLEAN DEFAULT 0",
            "notified_1d": "ALTER TABLE users ADD COLUMN notified_1d BOOLEAN DEFAULT 0",
            "notified_3h": "ALTER TABLE users ADD COLUMN notified_3h BOOLEAN DEFAULT 0",
        }
        for col, stmt in user_migrations.items():
            if col not in existing_user_cols:
                conn.execute(text(stmt))
                logger.info(f"Migration: added users.{col}")

        profile_migrations = {
            "xui_client_id": "ALTER TABLE vpn_profiles ADD COLUMN xui_client_id VARCHAR",
            "xui_email": "ALTER TABLE vpn_profiles ADD COLUMN xui_email VARCHAR",
            "xui_sub_id": "ALTER TABLE vpn_profiles ADD COLUMN xui_sub_id VARCHAR",
            "xui_inbound_ids": "ALTER TABLE vpn_profiles ADD COLUMN xui_inbound_ids VARCHAR",
            "status": "ALTER TABLE vpn_profiles ADD COLUMN status VARCHAR DEFAULT 'active'",
            "updated_at": "ALTER TABLE vpn_profiles ADD COLUMN updated_at DATETIME",
        }
        for col, stmt in profile_migrations.items():
            if col not in existing_profile_cols:
                conn.execute(text(stmt))
                logger.info(f"Migration: added vpn_profiles.{col}")

        order_migrations = {
            "duration_days": "ALTER TABLE orders ADD COLUMN duration_days INTEGER",
            "tariff_label": "ALTER TABLE orders ADD COLUMN tariff_label VARCHAR",
        }
        for col, stmt in order_migrations.items():
            if col not in existing_order_cols:
                conn.execute(text(stmt))
                logger.info(f"Migration: added orders.{col}")

        _migrate_legacy_profiles(conn)


def _migrate_legacy_profiles(conn):
    rows = conn.execute(text(
        "SELECT id, user_id, vless_profile_data, vless_profile_id "
        "FROM vpn_profiles WHERE vless_profile_data IS NOT NULL AND xui_email IS NULL"
    )).fetchall()

    for row in rows:
        try:
            data = json.loads(row.vless_profile_data)
            if not isinstance(data, dict):
                continue

            xui_email = data.get("email", "")
            xui_client_id = data.get("client_id", "")
            xui_sub_id = data.get("sub_id", "")
            inbound_ids = json.dumps(data.get("inbound_ids", config.INBOUND_IDS or [config.INBOUND_ID]))

            conn.execute(text(
                "UPDATE vpn_profiles SET "
                "xui_email = :email, xui_client_id = :client_id, "
                "xui_sub_id = :sub_id, xui_inbound_ids = :inbound_ids, "
                "status = 'active' "
                "WHERE id = :id"
            ), {
                "email": xui_email,
                "client_id": xui_client_id,
                "sub_id": xui_sub_id,
                "inbound_ids": inbound_ids,
                "id": row.id,
            })
            logger.info(f"Migration: migrated profile {row.id} (email={xui_email})")
        except Exception as e:
            logger.warning(f"Migration: failed to migrate profile {row.id}: {e}")


async def init_db():
    Base.metadata.create_all(engine)
    run_migrations()
    logger.info("Database initialized with migrations")


async def get_user(telegram_id: int):
    with Session() as session:
        user = session.query(User).filter_by(telegram_id=telegram_id).first()
        if user:
            original_end = user.subscription_end
            user.subscription_end = validate_and_fix_subscription_date(user.subscription_end)
            if user.subscription_end != original_end:
                session.commit()
        return user


async def create_user(telegram_id: int, full_name: str, username: str = None, is_admin: bool = False):
    with Session() as session:
        subscription_end = validate_and_fix_subscription_date(
            datetime.utcnow() + timedelta(days=config.TRIAL_DAYS)
        )
        user = User(
            telegram_id=telegram_id,
            full_name=full_name,
            username=username,
            subscription_end=subscription_end,
            is_admin=is_admin,
        )
        session.add(user)
        session.commit()
        logger.info(f"New user created: {telegram_id}, trial until {subscription_end}")
        return user


async def get_all_users(with_subscription: bool = None):
    with Session() as session:
        query = session.query(User)
        now = datetime.utcnow()
        if with_subscription is not None:
            if with_subscription:
                query = query.filter(User.subscription_end > now)
            else:
                query = query.filter(User.subscription_end <= now)
        return query.all()


async def get_user_stats():
    with Session() as session:
        total = session.query(func.count(User.id)).scalar()
        with_sub = session.query(func.count(User.id)).filter(
            User.subscription_end > datetime.utcnow()
        ).scalar()
        return total, with_sub, total - with_sub


async def get_active_profile(user_id: int):
    with Session() as session:
        return session.query(VPNProfile).filter_by(
            user_id=user_id, is_active=True, status='active'
        ).order_by(VPNProfile.id.desc()).first()


async def get_profile_by_user(telegram_id: int):
    with Session() as session:
        user = session.query(User).filter_by(telegram_id=telegram_id).first()
        if not user:
            return None, None
        profile = session.query(VPNProfile).filter_by(
            user_id=user.id, is_active=True
        ).order_by(VPNProfile.id.desc()).first()
        return user, profile


def save_profile(profile):
    with Session() as session:
        session.merge(profile)
        session.commit()


def save_user(user):
    with Session() as session:
        session.merge(user)
        session.commit()


async def create_order(telegram_id: int, months: int, amount: int,
                       duration_days: int | None = None, tariff_label: str | None = None):
    with Session() as session:
        user = session.query(User).filter_by(telegram_id=telegram_id).first()
        if not user:
            return None

        profile = session.query(VPNProfile).filter_by(
            user_id=user.id, is_active=True
        ).order_by(VPNProfile.id.desc()).first()

        for _ in range(10):
            payment_code = _generate_payment_code()
            exists = session.query(Order).filter_by(payment_code=payment_code).first()
            if not exists:
                break
        else:
            payment_code = f"VPN-{uuid.uuid4().hex[:8].upper()}"

        order = Order(
            user_id=user.id,
            vpn_profile_id=profile.id if profile else None,
            months=months,
            amount=amount,
            duration_days=duration_days or months * 30,
            tariff_label=tariff_label or f"{months} мес.",
            payment_code=payment_code,
            status='created',
        )
        session.add(order)
        session.commit()
        return order


async def get_order(order_uuid: str):
    with Session() as session:
        return session.query(Order).filter_by(order_uuid=order_uuid).first()


async def mark_order_paid(order_uuid: str, telegram_id: int):
    with Session() as session:
        order = session.query(Order).filter_by(order_uuid=order_uuid).first()
        user = session.query(User).filter_by(telegram_id=telegram_id).first()
        if not order or not user or order.user_id != user.id or order.status != 'created':
            return None
        order.status = 'pending_review'
        order.paid_at = datetime.now(timezone.utc)
        session.commit()
        return order


async def get_pending_orders():
    with Session() as session:
        return session.query(Order).filter_by(status='pending_review').order_by(Order.paid_at.asc()).all()


async def cancel_order(order_uuid: str, admin_telegram_id: int):
    with Session() as session:
        order = session.query(Order).filter_by(order_uuid=order_uuid).first()
        if not order or order.status != 'pending_review':
            return None
        order.status = 'cancelled'
        order.verified_at = datetime.utcnow()
        order.verified_by = admin_telegram_id
        session.commit()
        return order


async def approve_order(order_uuid: str, admin_telegram_id: int):
    with Session() as session:
        order = session.query(Order).filter_by(order_uuid=order_uuid).first()
        if not order or order.status != 'pending_review':
            return None

        user = session.query(User).filter_by(id=order.user_id).first()
        if not user:
            return None

        profile = session.query(VPNProfile).filter_by(
            id=order.vpn_profile_id
        ).first() if order.vpn_profile_id else None

        now = datetime.utcnow()
        user.subscription_end = validate_and_fix_subscription_date(user.subscription_end)
        duration_days = order.duration_days or order.months * 30

        if user.subscription_end > now:
            user.subscription_end += timedelta(days=duration_days)
        else:
            user.subscription_end = now + timedelta(days=duration_days)

        user.subscription_end = validate_and_fix_subscription_date(user.subscription_end)
        user.notified = False
        user.notified_3d = False
        user.notified_1d = False
        user.notified_3h = False

        if profile:
            profile.subscription_end = user.subscription_end

        order.status = 'approved'
        order.verified_at = now
        order.verified_by = admin_telegram_id
        session.commit()
        return order


# ─── Legacy helpers (used by app.py) ───────────────────────────────────────

async def delete_user_profile(telegram_id: int):
    with Session() as session:
        user = session.query(User).filter_by(telegram_id=telegram_id).first()
        if user:
            user.vless_profile_data = None
            user.notified = False
            session.commit()

async def update_subscription(telegram_id: int, months: int):
    with Session() as session:
        user = session.query(User).filter_by(telegram_id=telegram_id).first()
        if user:
            now = datetime.utcnow()
            user.subscription_end = validate_and_fix_subscription_date(user.subscription_end)
            if user.subscription_end > now:
                user.subscription_end += timedelta(days=months * 30)
            else:
                user.subscription_end = now + timedelta(days=months * 30)
            user.subscription_end = validate_and_fix_subscription_date(user.subscription_end)
            user.notified = False
            session.commit()
            return True
        return False
