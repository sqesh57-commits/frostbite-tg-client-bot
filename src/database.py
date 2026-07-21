from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, ForeignKey, func, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime, timedelta, timezone
import logging
import uuid
import random
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
    subscription_end = Column(DateTime)
    vless_profile_id = Column(String)
    vless_profile_data = Column(String)
    is_admin = Column(Boolean, default=False)
    notified = Column(Boolean, default=False)


class VPNProfile(Base):
    __tablename__ = 'vpn_profiles'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    profile_uuid = Column(String, unique=True, default=lambda: str(uuid.uuid4()))
    name = Column(String)
    vless_profile_id = Column(String)
    vless_profile_data = Column(String)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    subscription_end = Column(DateTime)


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
    """Normalize datetime-like values to naive UTC for SQLite storage/comparison."""
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


async def init_db():
    Base.metadata.create_all(engine)
    ensure_order_columns()
    logger.info("Database tables created")


def ensure_order_columns():
    """Add order columns used by configurable test tariffs to existing SQLite DBs."""
    existing_columns = {column["name"] for column in inspect(engine).get_columns("orders")}
    migrations = {
        "duration_days": "ALTER TABLE orders ADD COLUMN duration_days INTEGER",
        "tariff_label": "ALTER TABLE orders ADD COLUMN tariff_label VARCHAR",
    }
    with engine.begin() as connection:
        for column_name, statement in migrations.items():
            if column_name not in existing_columns:
                connection.execute(text(statement))


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
        subscription_end = validate_and_fix_subscription_date(datetime.utcnow() + timedelta(days=config.TRIAL_DAYS))
        user = User(
            telegram_id=telegram_id,
            full_name=full_name,
            username=username,
            subscription_end=subscription_end,
            is_admin=is_admin
        )
        session.add(user)
        session.commit()
        logger.info(f"New user created: {telegram_id}")
        return user


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


async def get_all_users(with_subscription: bool = None):
    with Session() as session:
        query = session.query(User)
        now = datetime.utcnow()
        if with_subscription is not None:
            if with_subscription:
                query = query.filter(User.subscription_end > now)
            else:
                query = query.filter(User.subscription_end <= now)

        users = query.all()
        dates_changed = False
        for user in users:
            original_end = user.subscription_end
            user.subscription_end = validate_and_fix_subscription_date(user.subscription_end)
            if user.subscription_end != original_end:
                dates_changed = True

        if dates_changed:
            session.commit()

        return users


async def get_user_stats():
    with Session() as session:
        total = session.query(func.count(User.id)).scalar()
        with_sub = session.query(func.count(User.id)).filter(
            User.subscription_end > datetime.utcnow()
        ).scalar()
        without_sub = total - with_sub
        return total, with_sub, without_sub


def validate_and_fix_subscription_date(subscription_end) -> datetime:
    now = datetime.utcnow()
    default = now + timedelta(days=3)
    subscription_end = to_naive_utc(subscription_end)
    if subscription_end is None:
        return default

    if subscription_end < datetime(2020, 1, 1) or subscription_end > now + timedelta(days=3650):
        return default

    return subscription_end


def _generate_payment_code() -> str:
    return f"VPN-{random.randint(100000, 999999)}"


async def get_or_create_default_vpn_profile(user: User):
    with Session() as session:
        profile = session.query(VPNProfile).filter_by(user_id=user.id, is_active=True).order_by(VPNProfile.id.asc()).first()
        if profile:
            return profile

        profile = VPNProfile(
            user_id=user.id,
            name=user.full_name or f"Profile {user.telegram_id}",
            vless_profile_id=user.vless_profile_id,
            vless_profile_data=user.vless_profile_data,
            subscription_end=validate_and_fix_subscription_date(user.subscription_end),
        )
        session.add(profile)
        session.commit()
        return profile


async def create_order(
    telegram_id: int,
    months: int,
    amount: int,
    duration_days: int | None = None,
    tariff_label: str | None = None,
):
    with Session() as session:
        user = session.query(User).filter_by(telegram_id=telegram_id).first()
        if not user:
            return None

        profile = session.query(VPNProfile).filter_by(user_id=user.id, is_active=True).order_by(VPNProfile.id.asc()).first()
        if not profile:
            profile = VPNProfile(
                user_id=user.id,
                name=user.full_name or f"Profile {user.telegram_id}",
                vless_profile_id=user.vless_profile_id,
                vless_profile_data=user.vless_profile_data,
                subscription_end=validate_and_fix_subscription_date(user.subscription_end),
            )
            session.add(profile)
            session.flush()

        for _ in range(10):
            payment_code = _generate_payment_code()
            exists = session.query(Order).filter_by(payment_code=payment_code).first()
            if not exists:
                break
        else:
            payment_code = f"VPN-{uuid.uuid4().hex[:8].upper()}"

        order = Order(
            user_id=user.id,
            vpn_profile_id=profile.id,
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
        profile = session.query(VPNProfile).filter_by(id=order.vpn_profile_id).first() if order.vpn_profile_id else None
        if not user:
            return None

        now = datetime.utcnow()
        user.subscription_end = validate_and_fix_subscription_date(user.subscription_end).replace(tzinfo=None)
        duration_days = order.duration_days or order.months * 30
        if user.subscription_end > now:
            user.subscription_end += timedelta(days=duration_days)
        else:
            user.subscription_end = now + timedelta(days=duration_days)
        user.subscription_end = validate_and_fix_subscription_date(user.subscription_end).replace(tzinfo=None)
        user.notified = False

        if profile:
            profile.subscription_end = user.subscription_end
            profile.vless_profile_id = user.vless_profile_id
            profile.vless_profile_data = user.vless_profile_data

        order.status = 'approved'
        order.verified_at = now
        order.verified_by = admin_telegram_id
        session.commit()
        return order
