import telebot
from instagrapi import Client
import threading
import time
from keep_alive import keep_alive

keep_alive()  # render ke liye

BOT_TOKEN = "8054752328:AAHW91DOipkoYVHVZuOBB5VId_DB9OTjRCw"
bot = telebot.TeleBot(BOT_TOKEN)

USER = {}
GC_LIST = {}
SELECTED_GC = {}
SPAM = {}

# ---------------------------
# Start Command
# ---------------------------
@bot.message_handler(commands=['start'])
def start(msg):
    chat = msg.chat.id
    USER[chat] = {"step": "ask_username"}
    bot.reply_to(msg,
                 "👋 Welcome!\nSend your Instagram **username**:")


# ---------------------------
# Handle Steps
# ---------------------------
@bot.message_handler(func=lambda m: True)
def steps(msg):
    chat = msg.chat.id

    # Ask username
    if USER.get(chat, {}).get("step") == "ask_username":
        USER[chat]["username"] = msg.text.strip()
        USER[chat]["step"] = "ask_password"
        bot.reply_to(msg, "🔐 Send your Instagram **password**:")
        return

    # Ask password
    if USER.get(chat, {}).get("step") == "ask_password":
        USER[chat]["password"] = msg.text.strip()
        USER[chat]["step"] = "login"
        bot.reply_to(msg, "⏳ Logging into Instagram…")
        return login_user(msg)

    # Selecting GC
    if USER.get(chat, {}).get("step") == "select_gc":
        try:
            index = int(msg.text) - 1
            SELECTED_GC[chat] = GC_LIST[chat][index]
            USER[chat]["step"] = "ask_message"

            bot.reply_to(msg,
                f"✅ Selected: {SELECTED_GC[chat].thread_title}\n"
                "✍️ Send spam message:")

        except:
            bot.reply_to(msg, "❌ Invalid number.")
        return

    # Ask spam message
    if USER.get(chat, {}).get("step") == "ask_message":
        SPAM[chat] = {"text": msg.text, "run": True}
        USER[chat]["step"] = "spamming"

        bot.reply_to(msg, "🚀 Spam Started!\nSend /stop to stop.")

        threading.Thread(target=spam_loop, args=(chat,), daemon=True).start()
        return


# ---------------------------
# LOGIN FUNCTION (100% FIXED)
# ---------------------------
def login_user(msg):
    chat = msg.chat.id
    cl = Client()

    try:
        # SAFE LOGIN SETTINGS (PREVENT BLOCK)
        cl.set_locale("en_US")
        cl.set_country("IN")
        cl.set_timezone_offset(19800)
        
        cl.login(USER[chat]["username"], USER[chat]["password"])
        USER[chat]["client"] = cl

        bot.reply_to(msg, "✅ Login Successful!\n⏳ Fetching your group chats…")

    except Exception as e:
        bot.reply_to(msg, f"❌ Login Failed:\n`{e}`")
        USER[chat]["step"] = "ask_username"
        return

    # GET GROUP CHATS
    threads = cl.direct_threads(amount=50)
    groups = [t for t in threads if t.thread_type in ("group", "multi_participant")]

    if not groups:
        bot.send_message(chat, "❌ No group chats found.")
        USER[chat]["step"] = "ask_username"
        return

    GC_LIST[chat] = groups

    txt = "📌 Your Group Chats:\n\n"
    for i, g in enumerate(groups):
        txt += f"{i+1}. {g.thread_title}\n"

    bot.send_message(chat, txt + "\n➡️ Send the GC number:")
    USER[chat]["step"] = "select_gc"


# ---------------------------
# SPAM LOOP
# ---------------------------
def spam_loop(chat):
    cl = USER[chat]["client"]
    gc = SELECTED_GC[chat]

    while SPAM[chat]["run"]:
        try:
            cl.direct_send(SPAM[chat]["text"], [gc.thread_id])
        except:
            pass

        time.sleep(10)


# ---------------------------
# STOP COMMAND
# ---------------------------
@bot.message_handler(commands=['stop'])
def stop(msg):
    chat = msg.chat.id
    if SPAM.get(chat):
        SPAM[chat]["run"] = False
        bot.reply_to(msg, "🛑 Spam stopped.")
    else:
        bot.reply_to(msg, "❌ No spam running.")


# ---------------------------
# START BOT
# ---------------------------
bot.polling(non_stop=True, skip_pending=True)
