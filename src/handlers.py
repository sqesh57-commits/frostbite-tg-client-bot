import asyncio
import logging
import json
import io
import qrcode
import time
from datetime import datetime, timedelta, timezone
from aiogram import Dispatcher, Router, F, Bot
from aiogram.types import Message, CallbackQuery, LabeledPrice, PreCheckoutQuery, BufferedInputFile
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import config
from database import (
    get_user, create_user, update_subscription,
    User, Session
)
from functions import (
    create_vless_profile, generate_vless_url,
    get_user_stats, generate_sub_url, update_client_expiry, get_safe_expiry_timestamp,
    force_update_profile_expiry, get_client_links
)

logger = logging.getLogger(__name__)

router = Router()

MAX_MESSAGE_LENGTH = 4096

profile_create_attempts: dict[int, float] = {}


def is_profile_create_admin(user: User) -> bool:
    return bool(user.is_admin) or user.telegram_id in config.ADMINS


def validate_profile_create(user: User) -> tuple[bool, str | None, str | None]:
    if not config.BOT_REQUIRE_ADMIN_FOR_PROFILE_CREATE:
        return True, None, None

    if is_profile_create_admin(user):
        return True, None, None

    if user.telegram_id in config.BOT_BLOCKED_PROFILE_CREATE_IDS:
        return (
            False,
            "⛔ Создание VPN-профиля для вашего аккаунта ограничено. Обратитесь в поддержку.",
            "blocked",
        )

    if user.subscription_end.replace(tzinfo=None) < datetime.utcnow():
        return False, "⚠️ Подписка истекла! Продлите подписку.", "inactive_subscription"

    if user.vless_profile_data:
        return False, "⚠️ VPN-профиль уже создан для вашего аккаунта.", "profile_exists"

    if config.BOT_MAX_PROFILES_PER_USER <= 0:
        return (
            False,
            "⛔ Создание VPN-профилей временно ограничено. Попробуйте позже.",
            "profile_limit_disabled",
        )

    now = time.monotonic()
    last_attempt = profile_create_attempts.get(user.telegram_id)
    if (
        last_attempt is not None
        and now - last_attempt < config.BOT_PROFILE_CREATE_RATE_LIMIT_SECONDS
    ):
        return False, "⏳ Слишком много попыток создать профиль. Попробуйте позже.", "rate_limited"

    profile_create_attempts[user.telegram_id] = now
    return True, None, None


async def deny_profile_create(message_target, user: User, reason: str, message_text: str):
    await message_target.answer(message_text)
    logger.warning(
        "Profile creation denied: user_id=%s reason=%s has_active_subscription=%s has_profile=%s",
        user.id,
        reason,
        user.subscription_end.replace(tzinfo=None) >= datetime.utcnow(),
        bool(user.vless_profile_data),
    )


def format_user_stats(stats: dict) -> str:
    def format_traffic(value: int) -> str:
        megabytes = value / 1024 / 1024
        if megabytes < 1024:
            return f"{megabytes:.2f} MB"
        return f"{megabytes / 1024:.2f} GB"

    upload = format_traffic(stats.get('upload', 0))
    download = format_traffic(stats.get('download', 0))

    return (
        "📊 **Ваша статистика:**\n\n"
        f"🔼 Загружено: `{upload}`\n"
        f"🔽 Скачано: `{download}`\n"
    )


async def show_menu(bot: Bot, chat_id: int, message_id: int = None):
    user = await get_user(chat_id)
    if not user:
        return

    status = "Активна" if user.subscription_end > datetime.utcnow() else "Истекла"
    expire_date = user.subscription_end.strftime("%d-%m-%Y %H:%M") if status == "Активна" else status

    text = (
        f"**Имя профиля**: `{user.full_name}`\n"
        f"**Id**: `{user.telegram_id}`\n"
        f"**Подписка**: `{status}`\n"
        f"**Дата окончания подписки**: `{expire_date}`"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="💵 Продлить" if status == "Активна" else "💵 Оплатить", callback_data="renew_sub")
    builder.button(text="✅ Подключить", callback_data="connect")
    builder.button(text="📊 Статистика", callback_data="stats")
    builder.button(text="ℹ️ Помощь", callback_data="help")
    builder.adjust(2, 2, 1)

    if message_id:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=builder.as_markup(),
            parse_mode='Markdown'
        )
    else:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=builder.as_markup(),
            parse_mode='Markdown'
        )


@router.message(Command("start"))
async def start_cmd(message: Message, bot: Bot):
    logger.info(f"Start command from {message.from_user.id}")
    user = await get_user(message.from_user.id)

    update_data = {}
    if user:
        if user.full_name != message.from_user.full_name:
            update_data["full_name"] = message.from_user.full_name
        if user.username != message.from_user.username:
            update_data["username"] = message.from_user.username
    else:
        user = await create_user(
            telegram_id=message.from_user.id,
            full_name=message.from_user.full_name,
            username=message.from_user.username,
        )
        await message.answer(
            f"Добро пожаловать в VPN бота `{(await bot.get_me()).full_name}`!\n"
            "Вам предоставлен **бесплатный** тестовый период на **3 дня**!",
            parse_mode='Markdown'
        )
        await asyncio.sleep(2)

    if update_data:
        with Session() as session:
            db_user = session.query(User).get(user.id)
            for key, value in update_data.items():
                setattr(db_user, key, value)
            session.commit()

    await show_menu(bot, message.from_user.id)


@router.message(Command("menu"))
async def menu_cmd(message: Message, bot: Bot):
    user = await get_user(message.from_user.id)
    if not user:
        await start_cmd(message, bot)
        return

    update_data = {}
    if user.full_name != message.from_user.full_name:
        update_data["full_name"] = message.from_user.full_name
    if user.username != message.from_user.username:
        update_data["username"] = message.from_user.username

    if update_data:
        with Session() as session:
            db_user = session.query(User).get(user.id)
            for key, value in update_data.items():
                setattr(db_user, key, value)
            session.commit()

    await show_menu(bot, message.from_user.id)


@router.message(Command("renew"))
async def renew_cmd(message: Message, bot: Bot):
    user = await get_user(message.from_user.id)
    if not user:
        await start_cmd(message, bot)
        return

    builder = InlineKeyboardBuilder()
    for months in sorted(config.PRICES.keys()):
        price_info = config.PRICES[months]
        final_price = config.calculate_price(months)
        discount_text = ""
        if price_info["discount_percent"] > 0:
            discount_text = f" (-{price_info['discount_percent']}%)"
        button_text = f"{months} мес. - {final_price} руб.{discount_text}"
        builder.button(text=button_text, callback_data=f"pay_{months}")
    builder.button(text="⬅️ Назад", callback_data="back_to_menu")
    builder.adjust(1)

    await message.answer(
        "💵 **Выберите период подписки:**",
        reply_markup=builder.as_markup(),
        parse_mode='Markdown'
    )


@router.message(Command("connect"))
async def connect_cmd(message: Message, bot: Bot):
    user = await get_user(message.from_user.id)
    if not user:
        await start_cmd(message, bot)
        return

    if user.subscription_end < datetime.utcnow():
        await message.answer("⚠️ Подписка истекла! Продлите подписку.")
        return

    if not user.vless_profile_data:
        can_create, deny_message, deny_reason = validate_profile_create(user)
        if not can_create:
            await deny_profile_create(message, user, deny_reason, deny_message)
            return

        await message.answer("⚙️ Создаем ваш VPN профиль...")
        expiry_time = get_safe_expiry_timestamp(user.subscription_end)
        profile_data = await create_vless_profile(user.telegram_id, expiry_time)

        if profile_data:
            with Session() as session:
                db_user = session.query(User).filter_by(telegram_id=user.telegram_id).first()
                if db_user:
                    db_user.vless_profile_data = json.dumps(profile_data)
                    session.commit()
            user = await get_user(user.telegram_id)
        else:
            await message.answer("🛑 Ошибка при создании профиля. Попробуйте позже.")
            return

    profile_data = safe_json_loads(user.vless_profile_data, default={})
    if not profile_data:
        await message.answer("⚠️ У вас пока нет созданного профиля.")
        return

    try:
        email = profile_data.get("email")
        if email:
            current_expiry_time = get_safe_expiry_timestamp(user.subscription_end)
            if current_expiry_time > 0:
                await force_update_profile_expiry(email, user.subscription_end)
    except Exception as e:
        logger.error(f"Error auto-updating profile expiry: {e}")

    sub_id = profile_data.get("sub_id")
    sub_url = generate_sub_url(sub_id) if sub_id else ""

    # Get VLESS link from 3x-ui API
    vless_url = ""
    if sub_id:
        links = await get_client_links(sub_id)
        for link in links:
            if isinstance(link, str) and link.startswith("vless://"):
                vless_url = link
                break
    if not vless_url:
        vless_url = sub_url

    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(sub_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0)
    photo = BufferedInputFile(img_byte_arr.getvalue(), filename="qr.png")

    text = (
        "📲 Как подключить VPN\n"
        "1. Нажмите кнопку «Подключиться»\n"
        "Откроется страница с вашим VPN-профилем.\n\n"
        "2. Пролистайте страницу вниз\n"
        "Найдите кнопки с вашей операционной системой:\n"
        "📱 Android\n"
        "🍏 iPhone (iOS)\n\n"
        "3. Выберите свою систему\n"
        "Откроется список приложений.\n"
        "👉 Выберите любое приложение из списка.\n\n"
        "4. Установите приложение\n"
        "Если оно не установлено — скачайте его.\n\n"
        "5. Нажмите на выбранное приложение ещё раз\n\n"
        "Ключ добавится автоматически — вручную ничего вставлять не нужно.\n\n"
        "6. Подключитесь к VPN\n"
        "Откроется приложение — нажмите:\n"
        "👉 Подключиться / Connect\n\n"
        "✅ Готово\n"
        "VPN включён — интернет работает без ограничений 🚀\n\n"
        "💡 Если не получилось\n"
        "попробуйте другое приложение из списка\n"
        "или заново нажмите «Подключиться» в боте"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text='Подключится', url=sub_url)
    builder.button(text="⬅️ В меню", callback_data="back_to_menu")
    builder.adjust(1, 1)

    await message.answer_photo(
        photo=photo,
        caption=text,
        reply_markup=builder.as_markup(),
        parse_mode='Markdown'
    )


@router.message(Command("stats"))
async def stats_cmd(message: Message, bot: Bot):
    user = await get_user(message.from_user.id)
    if not user or not user.vless_profile_data:
        await message.answer("⚠️ Профиль не создан")
        return

    await message.answer("⚙️ Загружаем вашу статистику...")
    profile_data = safe_json_loads(user.vless_profile_data, default={})
    email = profile_data.get("email")
    if not email:
        await message.answer("⚠️ Данные профиля повреждены, пересоздайте подключение")
        return

    stats = await get_user_stats(email)
    if not stats:
        await message.answer("⚠️ Не удалось получить статистику. Попробуйте позже")
        return

    text = format_user_stats(stats)

    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ В меню", callback_data="back_to_menu")

    await message.answer(text, parse_mode='Markdown', reply_markup=builder.as_markup())


@router.message(Command("help"))
async def help_cmd(message: Message, bot: Bot):
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ В меню", callback_data="back_to_menu")

    text = "О боте:\n"

    await message.answer(text, parse_mode='HTML', reply_markup=builder.as_markup())


@router.callback_query(F.data == "help")
async def help_msg(callback: CallbackQuery):
    await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Назад", callback_data="back_to_menu")
    text = "О боте:\n"
    await callback.message.edit_text(text, parse_mode='HTML', reply_markup=builder.as_markup())


@router.callback_query(F.data == "renew_sub")
async def renew_subscription(callback: CallbackQuery):
    builder = InlineKeyboardBuilder()

    for months in sorted(config.PRICES.keys()):
        price_info = config.PRICES[months]
        final_price = config.calculate_price(months)
        discount_text = ""
        if price_info["discount_percent"] > 0:
            discount_text = f" (-{price_info['discount_percent']}%)"
        button_text = f"{months} мес. - {final_price} руб.{discount_text}"
        builder.button(text=button_text, callback_data=f"pay_{months}")

    builder.button(text="⬅️ Назад", callback_data="back_to_menu")
    builder.adjust(1)

    await callback.message.edit_text(
        "💵 **Выберите период подписки:**",
        reply_markup=builder.as_markup(),
        parse_mode='Markdown'
    )


@router.callback_query(F.data.startswith("pay_"))
async def process_payment(callback: CallbackQuery, bot: Bot):
    await callback.answer()

    try:
        months = int(callback.data.split("_")[1])
        if months not in config.PRICES:
            await callback.message.answer("❌ Неверный период подписки")
            return

        final_price = config.calculate_price(months)
        suffix = "месяц" if months == 1 else "месяца" if months in (2, 3, 4) else "месяцев"
        prices = [LabeledPrice(label=f"VPN подписка на {months} мес.", amount=final_price * 100)]
        if config.PAYMENT_TOKEN:
            await bot.send_invoice(
                chat_id=callback.from_user.id,
                title=f"VPN подписка на {months} месяцев",
                description=f"Доступ к VPN сервису на {months} {suffix}",
                payload=f"subscription_{months}",
                provider_token=config.PAYMENT_TOKEN,
                currency="RUB",
                prices=prices,
                start_parameter="create_subscription",
                need_email=True,
                need_phone_number=False
            )
        else:
            await callback.message.answer("❌ Оплата временно недоступна")
    except Exception as e:
        logger.error(f"Payment error: {e}")
        await callback.message.answer("❌ Ошибка при создании счета на оплату")


@router.pre_checkout_query()
async def process_pre_checkout_query(pre_checkout_query: PreCheckoutQuery, bot: Bot):
    payload = pre_checkout_query.invoice_payload
    if not payload.startswith("subscription_"):
        await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=False, error_message="Некорректный запрос")
        return

    try:
        months = int(payload.split("_")[1])
        if months not in config.PRICES:
            await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=False, error_message="Неверный период")
            return
    except (ValueError, IndexError):
        await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=False, error_message="Ошибка данных")
        return

    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)


@router.message(F.successful_payment)
async def process_successful_payment(message: Message, bot: Bot):
    try:
        payload = message.successful_payment.invoice_payload
        if payload.startswith("subscription_"):
            months = int(payload.split("_")[1])
            final_price = config.calculate_price(months)

            user = await get_user(message.from_user.id)
            if not user:
                await message.answer("❌ Ошибка: пользователь не найден")
                return

            now = datetime.utcnow()
            action_type = "продлена" if user.subscription_end > now else "куплена"

            success = await update_subscription(message.from_user.id, months)
            suffix = "месяц" if months == 1 else "месяца" if months in (2, 3, 4) else "месяцев"
            if success:
                updated_user = await get_user(message.from_user.id)

                if updated_user and updated_user.vless_profile_data:
                    try:
                        profile_data = safe_json_loads(updated_user.vless_profile_data, default={})
                        email = profile_data.get("email")
                        if email:
                            expiry_time = get_safe_expiry_timestamp(updated_user.subscription_end)
                            await update_client_expiry(email, expiry_time)
                    except Exception as e:
                        logger.error(f"Failed to update expiry time in 3x-ui: {e}")

                await message.answer(
                    f"✅ Оплата прошла успешно! Ваша подписка {action_type} на {months} {suffix}.\n\n"
                    "Спасибо за покупку! 🎉"
                )

                for admin_id in config.ADMINS:
                    try:
                        admin_message = (
                            f"{action_type.capitalize()} подписка пользователем "
                            f"`{user.full_name}` | `{user.telegram_id}` "
                            f"на {months} {suffix} - {final_price}₽"
                        )
                        await bot.send_message(admin_id, admin_message, parse_mode='Markdown')
                    except Exception as e:
                        logger.error(f"Failed to send notification to admin {admin_id}: {e}")
            else:
                await message.answer("❌ Ошибка при обновлении подписки")
    except Exception as e:
        logger.error(f"Successful payment processing error: {e}")
        await message.answer("❌ Ошибка при обработке платежа")


@router.callback_query(F.data == "connect")
async def connect_profile(callback: CallbackQuery):
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer("🛑 Ошибка профиля")
        return

    if user.subscription_end < datetime.utcnow():
        await callback.answer("⚠️ Подписка истекла! Продлите подписку.")
        return

    if not user.vless_profile_data:
        can_create, deny_message, deny_reason = validate_profile_create(user)
        if not can_create:
            await deny_profile_create(callback.message, user, deny_reason, deny_message)
            await callback.answer()
            return

        await callback.message.edit_text("⚙️ Создаем ваш VPN профиль...")
        expiry_time = get_safe_expiry_timestamp(user.subscription_end)
        profile_data = await create_vless_profile(user.telegram_id, expiry_time)

        if profile_data:
            with Session() as session:
                db_user = session.query(User).filter_by(telegram_id=user.telegram_id).first()
                if db_user:
                    db_user.vless_profile_data = json.dumps(profile_data)
                    session.commit()
            user = await get_user(user.telegram_id)
        else:
            await callback.message.answer("🛑 Ошибка при создании профиля. Попробуйте позже.")
            return

    profile_data = safe_json_loads(user.vless_profile_data, default={})
    if not profile_data:
        await callback.message.answer("⚠️ У вас пока нет созданного профиля.")
        return

    sub_id = profile_data.get("sub_id")
    sub_url = generate_sub_url(sub_id) if sub_id else ""

    # Get VLESS link from 3x-ui API
    vless_url = ""
    if sub_id:
        links = await get_client_links(sub_id)
        for link in links:
            if isinstance(link, str) and link.startswith("vless://"):
                vless_url = link
                break
    if not vless_url:
        vless_url = sub_url

    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(sub_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0)
    photo = BufferedInputFile(img_byte_arr.getvalue(), filename="qr.png")

    text = (
        "📲 Как подключить VPN\n"
        "1. Нажмите кнопку «Подключиться» или отсканируйте QR код\n"
        "Откроется страница с вашим VPN-профилем.\n\n"
        "2. Пролистайте страницу вниз\n"
        "Найдите кнопки с вашей операционной системой:\n"
        "📱 Android\n"
        "🍏 iPhone (iOS)\n\n"
        "3. Выберите свою систему\n"
        "Откроется список приложений.\n"
        "👉 Выберите любое приложение из списка.\n\n"
        "4. Установите приложение\n"
        "Если оно не установлено — скачайте его.\n\n"
        "5. Нажмите на выбранное приложение ещё раз\n\n"
        "Ключ добавится автоматически — вручную ничего вставлять не нужно.\n\n"
        "6. Подключитесь к VPN\n"
        "Откроется приложение — нажмите:\n"
        "👉 Подключиться / Connect\n\n"
        "✅ Готово\n"
        "VPN включён — интернет работает без ограничений 🚀\n\n"
        "💡 Если не получилось\n"
        "попробуйте другое приложение из списка\n"
        "или заново нажмите «Подключиться» в боте"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text='Подключится', url=sub_url)
    builder.button(text="⬅️ Назад", callback_data="back_to_menu")
    builder.adjust(1, 1)

    await callback.message.answer_photo(
        photo=photo,
        caption=text,
        reply_markup=builder.as_markup(),
        parse_mode='Markdown'
    )
    await callback.message.delete()


@router.callback_query(F.data == "stats")
async def user_stats(callback: CallbackQuery):
    user = await get_user(callback.from_user.id)
    if not user or not user.vless_profile_data:
        await callback.answer("⚠️ Профиль не создан")
        return
    await callback.message.edit_text("⚙️ Загружаем вашу статистику...")
    profile_data = safe_json_loads(user.vless_profile_data, default={})
    email = profile_data.get("email")
    if not email:
        await callback.message.edit_text("⚠️ Данные профиля повреждены, пересоздайте подключение")
        return

    stats = await get_user_stats(email)
    if not stats:
        await callback.message.edit_text("⚠️ Не удалось получить статистику. Попробуйте позже")
        return

    await callback.message.delete()
    text = format_user_stats(stats)
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Назад", callback_data="back_to_menu")
    await callback.message.answer(text, parse_mode='Markdown', reply_markup=builder.as_markup())


@router.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery, bot: Bot):
    await callback.answer()
    if callback.message.photo:
        await callback.message.delete()
        await show_menu(bot, callback.from_user.id)
    else:
        await show_menu(bot, callback.from_user.id, callback.message.message_id)


def setup_handlers(dp: Dispatcher):
    dp.include_router(router)
    logger.info("Handlers setup completed")


def safe_json_loads(data, default=None):
    if not data:
        return default
    try:
        return json.loads(data)
    except Exception:
        return default
