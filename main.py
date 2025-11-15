import telebot
from instagrapi import Client
from instagrapi.exceptions import ChallengeRequired, TwoFactorRequired
import threading
import time
from flask import Flask
import os

# ---------------------------
# BOT TOKEN (HARDCODED)
# ---------------------------
BOT_TOKEN = "8054752328:AAHW91DOipkoYVHVZuOBB5VId_DB9OTjRCw"  # <-- Replace with your Telegram bot token
bot = telebot.TeleBot(BOT_TOKEN, threaded=True)

# ---------------------------
# FLASK SERVER FOR RENDER HEALTH CHECK
# ---------------------------
server = Flask(__name__)

# ---------------------------
# GLOBAL DICTS
# ---------------------------
USERS = {}
GC_LIST = {}
SELECTED = {}
SPAM = {}

# ---------------------------
# CREATE INSTAGRAM CLIENT
# ---------------------------
def create_client(chat_id):
    cl = Client()
    cl.set_locale('en_US')
    cl.set_country('IN')
    cl.set_timezone_offset(19800)
    cl.set_device({
        "android_version": 26,
        "android_release": "8.0.0",
        "dpi": "420dpi",
        "resolution": "1080x1920",
        "manufacturer": "Xiaomi",
        "device": "whyred",
        "model": "Redmi Note 5 Pro",
        "cpu": "qcom",
    })
    session_file = f"{chat_id}_session.json"
    if os.path.exists(session_file):
        try: cl.load_settings(session_file)
        except: pass
    return cl

def save_session(cl, chat_id):
    try: cl.dump_settings(f"{chat_id}_session.json")
    except: pass

def tg_type(chat_id):
    try: bot.send_chat_action(chat_id, "typing")
    except: pass

def ig_typing_and_send(cl, thread, text):
    try:
        cl.direct_send("typing…", [thread.id])
        time.sleep(1.2)
    except: pass
    cl.direct_send(text, [thread.id])

# ---------------------------
# /start
# ---------------------------
@bot.message_handler(commands=["start"])
def start(msg):
    USERS[msg.chat.id] = {"step": "ask_username"}
    tg_type(msg.chat.id)
    bot.reply_to(msg, "👋 Send your Instagram **username**:")

@bot.message_handler(commands=["help"])
def help_cmd(msg):
    bot.reply_to(msg, "Use /start to begin login process.")

# ---------------------------
# MAIN HANDLER
# ---------------------------
@bot.message_handler(func=lambda m: True)
def main_handler(msg):
    chat = msg.chat.id
    text = msg.text.strip()
    if chat not in USERS: return bot.reply_to(msg, "Type /start")
    step = USERS[chat]["step"]

    if step == "ask_username":
        USERS[chat]["username"] = text
        USERS[chat]["step"] = "ask_password"
        bot.reply_to(msg, "🔐 Send your **password**:")
        return

    if step == "ask_password":
        USERS[chat]["password"] = text
        USERS[chat]["step"] = "logging"
        bot.reply_to(msg, "⏳ Logging into Instagram…")
        threading.Thread(target=login_attempt, args=(chat,), daemon=True).start()
        return

    if step == "select_gc":
        if not text.isdigit(): return bot.reply_to(msg, "❌ Send number only.")
        idx = int(text)-1
        groups = GC_LIST.get(chat, [])
        if idx<0 or idx>=len(groups): return bot.reply_to(msg, "❌ Wrong number.")
        SELECTED[chat] = groups[idx]
        USERS[chat]["step"] = "ask_message"
        bot.reply_to(msg, "✍️ Send message to spam:")
        return

    if step == "ask_message":
        SPAM[chat] = {"text": text, "running": True}
        USERS[chat]["step"] = "spamming"
        bot.reply_to(msg, "🚀 Spam started! Use /stop to stop.")
        threading.Thread(target=spam_loop, args=(chat,), daemon=True).start()
        return

    if step == "spamming":
        return bot.reply_to(msg, "Spam running… Use /stop.")

    if step == "awaiting_2fa":
        threading.Thread(target=complete_2fa, args=(chat, text), daemon=True).start()
        return

    if step == "awaiting_challenge":
        threading.Thread(target=complete_challenge, args=(chat, text), daemon=True).start()
        return

# ---------------------------
# LOGIN LOGIC
# ---------------------------
def login_attempt(chat):
    username = USERS[chat]["username"]
    password = USERS[chat]["password"]
    cl = create_client(chat)
    USERS[chat]["client_temp"] = cl
    try:
        cl.login(username, password)
        save_session(cl, chat)
        USERS[chat]["client"] = cl
        USERS[chat]["step"] = "logged_in"
        bot.send_message(chat, "✅ Login🌙successful!\nFetching your groups…")
        load_groups(chat)
        return
    except TwoFactorRequired:
        USERS[chat]["step"] = "awaiting_2fa"
        bot.send_message(chat, "🔐 Send your 2FA OTP:")
        return
    except ChallengeRequired:
        USERS[chat]["step"] = "awaiting_challenge"
        USERS[chat]["challenge_url"] = cl.last_json["challenge"]["url"]
        bot.send_message(chat, "📩 Check email/SMS & send code:")
        return
    except Exception as e:
        bot.send_message(chat, f"❌ Login failed:\n`{e}`", parse_mode="Markdown")
        USERS[chat]["step"] = "ask_username"

def complete_2fa(chat, code):
    cl = USERS[chat]["client_temp"]
    username = USERS[chat]["username"]
    password = USERS[chat]["password"]
    try:
        cl.two_factor_login(username, password, code)
        save_session(cl, chat)
        USERS[chat]["client"] = cl
        USERS[chat]["step"] = "logged_in"
        bot.send_message(chat, "🎉 OTP Verified!\nFetching groups…")
        load_groups(chat)
    except Exception as e:
        bot.send_message(chat, f"❌ Wrong OTP:\n`{e}`", parse_mode="Markdown")
        USERS[chat]["step"] = "ask_username"

def complete_challenge(chat, code):
    cl = USERS[chat]["client_temp"]
    url = USERS[chat]["challenge_url"]
    try:
        cl.challenge_send_security_code(url, code)
        save_session(cl, chat)
        USERS[chat]["client"] = cl
        USERS[chat]["step"] = "logged_in"
        bot.send_message(chat, "🎉 Verified! Fetching groups…")
        load_groups(chat)
    except Exception as e:
        bot.send_message(chat, f"❌ Challenge failed:\n`{e}`", parse_mode="Markdown")
        USERS[chat]["step"] = "ask_username"

# ---------------------------
# FETCH GROUPS
# ---------------------------
def load_groups(chat):
    cl = USERS[chat]["client"]
    try:
        threads = cl.direct_threads()
        groups = [t for t in threads if t.thread_type in ("group","multi_participant")]
        GC_LIST[chat] = groups
        txt = "📌 Your Group Chats:\n\n"
        for i,g in enumerate(groups):
            txt += f"{i+1}. {g.thread_title or 'Unnamed'}\n"
        bot.send_message(chat, txt + "\nSend GC number:")
        USERS[chat]["step"] = "select_gc"
    except Exception as e:
        bot.send_message(chat, f"❌ Error:\n`{e}`", parse_mode="Markdown")

# ---------------------------
# SPAM LOOP
# ---------------------------
def spam_loop(chat):
    cl = USERS[chat]["client"]
    thread = SELECTED[chat]
    text = SPAM[chat]["text"]
    while SPAM[chat]["running"]:
        try: ig_typing_and_send(cl, thread, text)
        except: pass
        time.sleep(10)

# ---------------------------
# /stop
# ---------------------------
@bot.message_handler(commands=["stop"])
def stop(msg):
    chat = msg.chat.id
    if chat in SPAM:
        SPAM[chat]["running"] = False
        bot.reply_to(msg, "🛑 Spam stopped.")
    else:
        bot.reply_to(msg, "No spam running.")

# ---------------------------
# FLASK HEALTH CHECK
# ---------------------------
@server.route("/")
def home():
    return "Bot Running", 200

# ---------------------------
# RUN BOT
# ---------------------------
if __name__ == "__main__":
    bot.remove_webhook()  # Remove any webhook before polling
    threading.Thread(target=lambda: server.run(host="0.0.0.0", port=10000), daemon=True).start()
    print("Bot started in polling mode…")
    bot.infinity_polling()
