import json
import asyncio
import logging
import coloredlogs
from config import config
from aiogram import Bot, Dispatcher
from aiogram.types import PreCheckoutQuery
from handlers import setup_handlers
from datetime import datetime, timedelta, timezone
from database import Session, User, init_db, get_all_users, delete_user_profile

# Настройка логирования
coloredlogs.install(level='info')
logger = logging.getLogger(__name__)

async def check_subscriptions(bot: Bot):
    """Проверка статуса подписок и отправка уведомлений"""
    while True:
        try:
            now = datetime.utcnow()
            users = await get_all_users()

            for user in users:
                if user.subscription_end - now < timedelta(days=1) and user.subscription_end >= now and not user.notified:
                    try:
                        await bot.send_message(
                            user.telegram_id,
                            "⚠️ Ваша подписка истекает через 24 часа! Продлите подписку, чтобы сохранить доступ."
                        )
                        with Session() as session:
                            db_user = session.query(User).filter_by(telegram_id=user.telegram_id).first()
                            if db_user:
                                db_user.notified = True
                                session.commit()
                    except Exception as e:
                        logger.warning(f"Notification error: {e}")

                if user.subscription_end <= now and user.vless_profile_data:
                    try:
                        await delete_user_profile(user.telegram_id)
                        await bot.send_message(
                            user.telegram_id,
                            "❌ Ваша подписка истекла! Профиль VPN деактивирован. Продлите подписку, чтобы создать новый."
                        )
                    except Exception as e:
                        logger.warning(f"Deactivation error: {e}")
        except Exception as e:
            logger.warning(f"Subscription check error: {e}")

        await asyncio.sleep(3600)

async def update_admins_status():
    """Обновляет статус администраторов в базе данных"""
    with Session() as session:
        session.query(User).update({User.is_admin: False})

        for admin_id in config.ADMINS:
            user = session.query(User).filter_by(telegram_id=admin_id).first()
            if user:
                user.is_admin = True
            else:
                new_admin = User(
                    telegram_id=admin_id,
                    full_name=f"Admin {admin_id}",
                    is_admin=True,
                    subscription_end=datetime.now(timezone.utc) + timedelta(days=365)
                )
                session.add(new_admin)

        session.commit()
    logger.info("Admin status updated in database")

async def setup_bot_commands(bot: Bot):
    """Регистрация команд бота в меню Telegram"""
    from aiogram.types import BotCommand
    
    commands = [
        BotCommand(command="start", description="🚀 Запуск бота"),
        BotCommand(command="menu", description="📋 Главное меню"),
        BotCommand(command="renew", description="💵 Продлить подписку"),
        BotCommand(command="connect", description="✅ Подключить VPN"),
        BotCommand(command="stats", description="📊 Статистика"),
        BotCommand(command="help", description="ℹ️ Справка"),
    ]
    
    try:
        await bot.set_my_commands(commands)
        logger.info("✅ Bot commands registered successfully")
    except Exception as e:
        logger.error(f"❌ Failed to register bot commands: {e}")

async def main():
    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher()

    logger.info(
        f"Bot starting. XUI_API_URL={config.XUI_API_URL}, "
        f"INBOUND_ID={config.INBOUND_ID}, XUI_SUB_PATH={config.XUI_SUB_PATH}"
    )
    
    try:
        await init_db()
        logger.info("✅ Database initialized")

        # Обновляем статус администраторов
        await update_admins_status()
    except Exception as e:
        logger.error(f"❌ Database initialization error: {e}")
        return
    
    try:
        # Регистрируем команды бота
        await setup_bot_commands(bot)
    except Exception as e:
        logger.error(f"❌ Bot commands setup error: {e}")
    
    try:
        setup_handlers(dp)
        logger.info("Handlers registered")
    except Exception as e:
        logger.error(f"Handler registration error: {e}")
        return

    try:
        asyncio.create_task(check_subscriptions(bot))
    except Exception as e:
        logger.error(f"Subscription check task failed to start: {e}")

    logger.info("Starting bot...")
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Bot start error: {e}")
        return

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Stopping bot...")
        exit(0)
    except Exception as e:
        logger.error(f"❌ Main loop error: {e}")
        exit(1)