"""One-time interactive Telegram login. Run this yourself in a terminal (it asks for your phone
number and the code Telegram sends you; nothing is stored except the Telethon session file).

    python reality_engine/scripts/tg_login.py
    python reality_engine/scripts/tg_login.py --qr

Uses TELEGRAM_API_ID / TELEGRAM_API_HASH from the environment. Writes reality_engine/data/telegram_session.session
(gitignored - it is a logged-in key to your account; never upload it to GitHub or Drive).
"""
import argparse
import asyncio
from contextlib import suppress
from getpass import getpass
import os
from pathlib import Path

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

SESSION = Path(__file__).resolve().parents[1] / "data" / "telegram_session"

async def login_qr(client):
    """Show a renewing QR in a local window, without saving the login token."""
    import tkinter as tk
    import qrcode

    window = tk.Tk()
    window.title("Reality Engine - Telegram login")
    window.attributes("-topmost", True)
    tk.Label(window, text="Telegram on your phone: Settings > Devices > Link Desktop Device",
             padx=20, pady=15).pack()
    canvas = tk.Canvas(window, bg="white", highlightthickness=0)
    canvas.pack(padx=20)
    status = tk.Label(window, text="Scan the QR below. It refreshes automatically.", pady=15)
    status.pack()
    closed = False
    pending = None

    def close():
        nonlocal closed
        closed = True

    window.protocol("WM_DELETE_WINDOW", close)
    try:
        while not closed:
            qr = await client.qr_login()
            matrix = qrcode.QRCode(border=4, error_correction=qrcode.constants.ERROR_CORRECT_M)
            matrix.add_data(qr.url)
            matrix.make(fit=True)
            cells = matrix.get_matrix()
            scale = 7
            canvas.configure(width=len(cells) * scale, height=len(cells) * scale)
            canvas.delete("all")
            for y, row in enumerate(cells):
                for x, black in enumerate(row):
                    if black:
                        canvas.create_rectangle(x * scale, y * scale, (x + 1) * scale,
                                                (y + 1) * scale, fill="black", outline="")
            window.update()
            pending = asyncio.create_task(qr.wait())
            while not pending.done() and not closed:
                window.update()
                await asyncio.sleep(0.05)
            if closed:
                return False
            try:
                await pending
                return True
            except asyncio.TimeoutError:
                continue
            except SessionPasswordNeededError:
                status.configure(text="QR approved. Enter your two-step password in the terminal.")
                window.update()
                await client.sign_in(password=getpass("Telegram two-step password: "))
                return True
        return False
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
            with suppress(asyncio.CancelledError):
                await pending
        window.destroy()


async def main(use_qr=False):
    client = TelegramClient(str(SESSION), int(os.environ["TELEGRAM_API_ID"]), os.environ["TELEGRAM_API_HASH"])
    try:
        await client.connect()
        if not await client.is_user_authorized():
            if use_qr:
                if not await login_qr(client):
                    print("Login window closed. Login was not completed.")
                    return
            else:
                await client.start()
        me = await client.get_me()
        print(f"Logged in as: {me.first_name} (session saved to {SESSION}.session)")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qr", action="store_true", help="Approve login by scanning a local QR window")
    args = parser.parse_args()
    asyncio.run(main(args.qr))
