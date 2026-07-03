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
    registration_date = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    subscription_end = Column(DateTime)
    vless_profile_id = Column(String)
    vless_profile_data = Column(String)
    is_admin = Column(Boolean, default=False)
    notified = Column(Boolean, default=False)


engine = create_engine(f'sqlite:///{DB_PATH}', echo=False)
Session = sessionmaker(bind=engine)


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
        subscription_end = validate_and_fix_subscription_date(datetime.now(timezone.utc) + timedelta(days=3))
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
            now = datetime.now(timezone.utc)
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
        if with_subscription is not None:
            if with_subscription:
                query = query.filter(User.subscription_end > datetime.now(timezone.utc))
            else:
                query = query.filter(User.subscription_end <= datetime.now(timezone.utc))
        return query.all()


async def get_user_stats():
    with Session() as session:
        total = session.query(func.count(User.id)).scalar()
        with_sub = session.query(func.count(User.id)).filter(
            User.subscription_end > datetime.now(timezone.utc)
        ).scalar()
        without_sub = total - with_sub
        return total, with_sub, without_sub


def validate_and_fix_subscription_date(subscription_end) -> datetime:
    now = datetime.now(timezone.utc)
    default = now + timedelta(days=3)

    if isinstance(subscription_end, str):
        try:
            subscription_end = datetime.fromisoformat(subscription_end)
        except Exception:
            return default

    if not isinstance(subscription_end, datetime):
        return default

    # Strip timezone for comparison (SQLite stores naive datetimes)
    sub = subscription_end.replace(tzinfo=None)
    now_naive = now.replace(tzinfo=None)

    if sub < datetime(2020, 1, 1) or sub > now_naive + timedelta(days=3650):
        return default

    return subscription_end
