from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, func
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime, timedelta, timezone
import logging
import os

logger = logging.getLogger(__name__)

Base = declarative_base()

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "users.db")
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


engine = create_engine(f'sqlite:///{DB_PATH}', echo=False)
Session = sessionmaker(bind=engine)


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
    logger.info("Database tables created")


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
        subscription_end = validate_and_fix_subscription_date(datetime.utcnow() + timedelta(days=3))
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
