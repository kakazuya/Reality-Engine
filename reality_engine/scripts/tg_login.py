"""One-time interactive Telegram login. Run this yourself in a terminal (it asks for your phone
number and the code Telegram sends you; nothing is stored except the Telethon session file).

    python reality_engine/scripts/tg_login.py

Uses TELEGRAM_API_ID / TELEGRAM_API_HASH from the environment. Writes reality_engine/data/telegram_session.session
(gitignored - it is a logged-in key to your account; never upload it to GitHub or Drive).
"""
import os
from pathlib import Path

from telethon.sync import TelegramClient

SESSION = Path(__file__).resolve().parents[1] / "data" / "telegram_session"

with TelegramClient(str(SESSION), int(os.environ["TELEGRAM_API_ID"]), os.environ["TELEGRAM_API_HASH"]) as client:
    me = client.get_me()
    print(f"Logged in as: {me.first_name} (session saved to {SESSION}.session)")
