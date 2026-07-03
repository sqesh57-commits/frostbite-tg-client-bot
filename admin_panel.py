import streamlit as st
import sqlite3
import os
import signal
import psutil
import subprocess
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(BASE_DIR, "src")
DB_PATH = os.path.join(BASE_DIR, "users.db")
LOG_PATH = os.path.join(BASE_DIR, "bot_error.log")
PID_PATH = os.path.join(BASE_DIR, "bot.pid")

ADMIN_PANEL_PASSWORD = os.getenv("ADMIN_PANEL_PASSWORD", "")
ENABLE_CODE_EDITOR = os.getenv("ENABLE_CODE_EDITOR", "false").lower() == "true"

st.set_page_config(page_title="3X-UI Bot Panel", layout="wide")

if ADMIN_PANEL_PASSWORD:
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if not st.session_state.authenticated:
        st.title("Вход в панель")
        password = st.text_input("Пароль", type="password")
        if st.button("Войти"):
            if password == ADMIN_PANEL_PASSWORD:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Неверный пароль")
        st.stop()
else:
    st.warning("ADMIN_PANEL_PASSWORD не установлен — панель доступна без авторизации!")


def get_bot_pid():
    if os.path.exists(PID_PATH):
        try:
            with open(PID_PATH, "r") as f:
                pid = int(f.read().strip())
            if psutil.pid_exists(pid):
                proc = psutil.Process(pid)
                cmdline = " ".join(proc.cmdline())
                if "app.py" in cmdline:
                    return pid
        except (ValueError, psutil.NoSuchProcess):
            pass
    return None


def save_pid(pid):
    with open(PID_PATH, "w") as f:
        f.write(str(pid))


def remove_pid():
    if os.path.exists(PID_PATH):
        os.remove(PID_PATH)


with st.sidebar:
    st.title("3X-UI Bot")
    menu_items = ["Мониторинг", "Логи бота"]
    if ENABLE_CODE_EDITOR:
        menu_items.insert(1, "Редактор кода")
    menu = st.radio("Навигация:", menu_items)

    st.divider()
    bot_pid = get_bot_pid()
    if bot_pid:
        st.success(f"Бот Онлайн (PID: {bot_pid})")
        if st.button("Остановить бота", use_container_width=True):
            try:
                os.kill(bot_pid, signal.SIGTERM)
                time.sleep(1)
                remove_pid()
            except ProcessLookupError:
                remove_pid()
            st.rerun()
    else:
        st.error("Бот Оффлайн")
        if st.button("Запустить бота", use_container_width=True):
            log_file = open(LOG_PATH, "a")
            proc = subprocess.Popen(
                ["python3", os.path.join(SRC_DIR, "app.py")],
                stdout=log_file, stderr=log_file,
                start_new_session=True
            )
            save_pid(proc.pid)
            time.sleep(2)
            st.rerun()

if menu == "Мониторинг":
    st.header("Мониторинг")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE,
                full_name TEXT,
                username TEXT,
                registration_date DATETIME,
                subscription_end DATETIME,
                vless_profile_id TEXT,
                vless_profile_data TEXT,
                is_admin BOOLEAN DEFAULT 0,
                notified BOOLEAN DEFAULT 0
            )
        """)
        conn.commit()

        total = conn.execute("SELECT COUNT(*) as cnt FROM users").fetchone()["cnt"]
        with_sub = conn.execute(
            "SELECT COUNT(*) as cnt FROM users WHERE subscription_end > datetime('now')"
        ).fetchone()["cnt"]
        without_sub = total - with_sub

        col1, col2, col3 = st.columns(3)
        col1.metric("Всего пользователей", total)
        col2.metric("С подпиской", with_sub)
        col3.metric("Без подписки", without_sub)
    finally:
        conn.close()

elif menu == "Редактор кода":
    if not ENABLE_CODE_EDITOR:
        st.error("Редактор кода отключён. Установите ENABLE_CODE_EDITOR=true для включения.")
    else:
        st.header("Редактор файлов")
        files = [f for f in os.listdir(SRC_DIR) if f.endswith('.py')]
        target = st.selectbox("Файл:", files)
        path = os.path.join(SRC_DIR, target)
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        new_content = st.text_area("Код:", content, height=500)
        if st.button("Сохранить"):
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_content)
            st.success("Файл обновлен!")

elif menu == "Логи бота":
    st.header("Журнал событий")
    if os.path.exists(LOG_PATH):
        with open(LOG_PATH, "r") as f:
            st.code(f.read()[-5000:], language="text")
    else:
        st.info("Файл логов не найден")
