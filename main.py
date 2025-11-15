import os
import time
import threading
import json
import telebot
from instagrapi import Client
from instagrapi.exceptions import TwoFactorRequired, ChallengeRequired

# ----------------------------
# CONFIG - replace this token
# ----------------------------
BOT_TOKEN = os.environ.get("TG_BOT_TOKEN") or "YOUR_TELEGRAM_BOT_TOKEN"
bot = telebot.TeleBot(BOT_TOKEN)

# ----------------------------
# per-user storage (in-memory + session files)
# ----------------------------
# Note: sessions are also saved to disk as "<chat_id>_session.json"
USERS = {}         # chat_id -> state dict (username/password/client/step/...)
GC_LIST = {}       # chat_id -> list of threads
SELECTED = {}      # chat_id -> selected thread object
SPAM = {}          # chat_id -> {"text":..., "running":True/False, "thread":Thread}

# ----------------------------
# keep alive (imported)
# ----------------------------
from keep_alive import keep_alive
keep_alive()

# ----------------------------
# Utility: create client for user (try load existing session)
# ----------------------------
def user_client(chat_id):
    cl = Client()
    session_file = f"{chat_id}_session.json"
    if os.path.exists(session_file):
        try:
            cl.load_settings(session_file)
        except Exception:
            pass
    # set locale/timezone to reduce challenge noise
    try:
        cl.set_locale("en_US")
        cl.set_country("IN")
        cl.set_timezone_offset(19800)  # IST
    except Exception:
        pass
    return cl

def save_session(cl, chat_id):
    try:
        cl.dump_settings(f"{chat_id}_session.json")
    except Exception as e:
        print("save_session error:", e)

# ----------------------------
# Typing helper (Telegram)
# ----------------------------
def tg_typing(chat_id):
    try:
        bot.send_chat_action(chat_id, "typing")
    except Exception:
        pass

# ----------------------------
# IG typing effect (fake) before sending actual message
# ----------------------------
def ig_typing_and_send(cl: Client, thread_object, text):
    # Try to send a small typing message first (makes it look like typing)
    try:
        # many accounts will just receive "typing…" text; keep short
        cl.direct_send("typing…", [thread_object.id])
        time.sleep(1.5)
    except Exception:
        pass
    # now send actual message
    cl.direct_send(text, [thread_object.id])

# ----------------------------
# /start command
# ----------------------------
@bot.message_handler(commands=['start'])
def cmd_start(msg):
    chat = msg.chat.id
    USERS[chat] = {"step":"ask_username"}
    tg_typing(chat)
    bot.reply_to(msg, "👋 Welcome! To login send your Instagram username.\n\n(You can also use /help)")

@bot.message_handler(commands=['help'])
def cmd_help(msg):
    text = (
        "How to use:\n"
        "1) /start → bot will ask username\n"
        "2) send username → then password\n"
        "3) bot attempts login (if IG requests OTP you will be asked)\n"
        "4) groups will be listed → send group number\n"
        "5) send the message to spam → bot will run in background every 10s\n"
        "6) /stop will stop your spam\n\n"
        "Note: If you prefer not to type password here, you can log in on your phone and copy session file to server."
    )
    bot.reply_to(msg, text)

# ----------------------------
# Main text handler (steps)
# ----------------------------
@bot.message_handler(func=lambda m: True)
def main_flow(msg):
    chat = msg.chat.id
    text = msg.text.strip()

    # if user not started, ask to /start
    if chat not in USERS:
        bot.reply_to(msg, "Type /start to begin.")
        return

    step = USERS[chat].get("step")

    # ask username
    if step == "ask_username":
        USERS[chat]["username"] = text
        USERS[chat]["step"] = "ask_password"
        tg_typing(chat)
        bot.reply_to(msg, "🔐 Now send your Instagram **password**:")
        return

    # ask password -> perform login attempt
    if step == "ask_password":
        USERS[chat]["password"] = text
        tg_typing(chat)
        bot.reply_to(msg, "⏳ Attempting to login to Instagram...")
        USERS[chat]["step"] = "logging"
        threading.Thread(target=attempt_login, args=(chat,), daemon=True).start()
        return

    # after groups shown, user should send group number
    if step == "select_gc":
        if not text.isdigit():
            bot.reply_to(msg, "❌ Send only the group number (e.g., 2).")
            return
        idx = int(text) - 1
        groups = GC_LIST.get(chat, [])
        if idx < 0 or idx >= len(groups):
            bot.reply_to(msg, "❌ Invalid number. Try again.")
            return
        SELECTED[chat] = groups[idx]
        USERS[chat]["step"] = "ask_message"
        bot.reply_to(msg, f"✅ Selected: {groups[idx].thread_title or 'Unnamed'}\n✍️ Now send the message to spam:")
        return

    # ask message -> start spam loop
    if step == "ask_message":
        message_text = text
        SPAM[chat] = {"text": message_text, "running": True}
        USERS[chat]["step"] = "spamming"
        bot.reply_to(msg, "🚀 Spam started! Use /stop to stop.")
        # start background spam thread
        t = threading.Thread(target=spam_loop, args=(chat,), daemon=True)
        SPAM[chat]["thread"] = t
        t.start()
        return

    # if user in spamming, catch other messages
    if step == "spamming":
        bot.reply_to(msg, "Bot is currently spamming. Send /stop to stop or /start to start new session.")
        return

    # If login waiting for otp or challenge, handle in special keys
    if step in ("awaiting_2fa", "awaiting_challenge"):
        # user is expected to send the OTP now
        if not text:
            bot.reply_to(msg, "Send the OTP code you received.")
            return
        if step == "awaiting_2fa":
            threading.Thread(target=complete_2fa, args=(chat, text), daemon=True).start()
            return
        if step == "awaiting_challenge":
            threading.Thread(target=complete_challenge, args=(chat, text), daemon=True).start()
            return

    # default fallback
    bot.reply_to(msg, "I didn't understand. Use /help")

# ----------------------------
# Attempt login (in background thread)
# ----------------------------
def attempt_login(chat):
    try:
        username = USERS[chat]["username"]
        password = USERS[chat]["password"]
    except KeyError:
        bot.send_message(chat, "❌ Missing username/password. Send /start to begin.")
        USERS.pop(chat, None)
        return

    cl = user_client(chat)
    # store client here temporarily
    USERS[chat]["client_temp"] = cl

    try:
        cl.login(username, password)
        # success
        save_session(cl, chat)
        USERS[chat]["client"] = cl
        USERS[chat]["step"] = "logged_in"
        bot.send_message(chat, "✅ Login successful! Fetching your group chats...")
        fetch_and_show_groups(chat)
        return

    except TwoFactorRequired:
        USERS[chat]["step"] = "awaiting_2fa"
        bot.send_message(chat, "🔐 Two-factor authentication required. Send the 2FA code you received (SMS/app).")
        return

    except ChallengeRequired:
        # challenge flow
        # store last_json challenge url for later
        try:
            chal = cl.last_json.get("challenge", {})
            chal_url = chal.get("url")
            USERS[chat]["challenge_url"] = chal_url
        except Exception:
            USERS[chat]["challenge_url"] = None

        USERS[chat]["step"] = "awaiting_challenge"
        bot.send_message(chat, "📩 Instagram wants to verify your login. Check your email/SMS and send the code here.")
        return

    except Exception as e:
        # other errors
        bot.send_message(chat, f"❌ Login Failed:\n`{e}`", parse_mode="Markdown")
        USERS[chat]["step"] = "ask_username"
        return

# ----------------------------
# Complete 2FA (background)
# ----------------------------
def complete_2fa(chat, otp_code):
    cl = USERS[chat].get("client_temp") or user_client(chat)
    username = USERS[chat].get("username")
    password = USERS[chat].get("password")
    try:
        # try two_factor_login (username,password,otp) - instagrapi method
        cl.two_factor_login(username, password, otp_code)
        save_session(cl, chat)
        USERS[chat]["client"] = cl
        USERS[chat]["step"] = "logged_in"
        bot.send_message(chat, "🎉 2FA success — logged in! Fetching group chats...")
        fetch_and_show_groups(chat)
    except Exception as e:
        bot.send_message(chat, f"❌ 2FA failed:\n`{e}`", parse_mode="Markdown")
        USERS[chat]["step"] = "ask_username"

# ----------------------------
# Complete challenge (background)
# ----------------------------
def complete_challenge(chat, otp_code):
    cl = USERS[chat].get("client_temp") or user_client(chat)
    chal_url = USERS[chat].get("challenge_url")
    if not chal_url:
        bot.send_message(chat, "❌ No challenge URL saved. Restart login with /start")
        USERS[chat]["step"] = "ask_username"
        return
    try:
        # challenge_send_security_code expects url and code in many builds
        # some versions accept (url, code) or method names may vary.
        # We'll try the common method names:
        try:
            result = cl.challenge_send_security_code(chal_url, otp_code)
        except TypeError:
            # older/newer instagrapi variants:
            result = cl.challenge_send_security_code(otp_code)
        # check last_json for success
        save_session(cl, chat)
        USERS[chat]["client"] = cl
        USERS[chat]["step"] = "logged_in"
        bot.send_message(chat, "🎉 Challenge solved — logged in! Fetching group chats...")
        fetch_and_show_groups(chat)
    except Exception as e:
        bot.send_message(chat, f"❌ Challenge failed:\n`{e}`", parse_mode="Markdown")
        USERS[chat]["step"] = "ask_username"

# ----------------------------
# Fetch groups and show to user
# ----------------------------
def fetch_and_show_groups(chat):
    cl = USERS[chat].get("client")
    if not cl:
        bot.send_message(chat, "❌ No IG client available. Restart login with /start")
        USERS[chat]["step"] = "ask_username"
        return
    try:
        threads = cl.direct_threads(amount=60)
        # filter groups and multi participant
        groups = [t for t in threads if (getattr(t, "thread_type", None) in ("group", "multi_participant"))]
        if not groups:
            bot.send_message(chat, "❌ No group chats found in this Instagram account.")
            USERS[chat]["step"] = "ask_username"
            return
        GC_LIST[chat] = groups
        # build list text
        txt = "📌 Your Group Chats:\n\n"
        for i, g in enumerate(groups):
            title = g.thread_title or "Unnamed"
            txt += f"{i+1}. {title}\n"
        bot.send_message(chat, txt + "\n➡️ Send the GC number to select.")
        USERS[chat]["step"] = "select_gc"
    except Exception as e:
        bot.send_message(chat, f"❌ Could not fetch threads:\n`{e}`", parse_mode="Markdown")
        USERS[chat]["step"] = "ask_username"

# ----------------------------
# Spam loop (per-user)
# ----------------------------
def spam_loop(chat):
    cl = USERS[chat].get("client")
    thread_obj = SELECTED.get(chat) or (GC_LIST.get(chat, [None])[0] if GC_LIST.get(chat) else None)
    if not cl or not thread_obj:
        bot.send_message(chat, "❌ Missing client or group. Stop.")
        return
    # run until flagged
    while SPAM.get(chat, {}).get("running", False):
        try:
            ig_typing_and_send(cl, thread_obj, SPAM[chat]["text"])
        except Exception as e:
            print("Spam send error:", e)
            # if error severe (like invalid session), stop
        time.sleep(10)  # 10s interval

# ----------------------------
# /stop command
# ----------------------------
@bot.message_handler(commands=['stop'])
def cmd_stop(msg):
    chat = msg.chat.id
    if SPAM.get(chat):
        SPAM[chat]["running"] = False
        bot.reply_to(msg, "🛑 Spam stopped.")
    else:
        bot.reply_to(msg, "⚠️ No spam running.")

# ----------------------------
# Run polling (only one instance!)
# ----------------------------
if __name__ == "__main__":
    print("Bot started. Polling...")
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
