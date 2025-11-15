import telebot
from instagrapi import Client
import threading
import time
from keep_alive import keep_alive

keep_alive()

BOT_TOKEN = "8054752328:AAHW91DOipkoYVHVZuOBB5VId_DB9OTjRCw"
bot = telebot.TeleBot(BOT_TOKEN)

USER = {}
GC_LIST = {}
SPAM = {}
SELECTED_GC = {}


# ---------------------------
# /start
# ---------------------------
@bot.message_handler(commands=['start'])
def start(msg):
    chat = msg.chat.id
    USER[chat] = {"step": "ask_username"}
    bot.reply_to(msg, "👋 Welcome!\nSend your Instagram **username**:")


# ---------------------------
# ALL TEXT HANDLER
# ---------------------------
@bot.message_handler(func=lambda m: True)
def flow(msg):
    chat = msg.chat.id

    # -------- Username Step --------
    if USER.get(chat, {}).get("step") == "ask_username":
        USER[chat]["username"] = msg.text.strip()
        USER[chat]["step"] = "ask_password"
        bot.reply_to(msg, "🔐 Send your Instagram **password**:")
        return

    # -------- Password Step --------
    if USER.get(chat, {}).get("step") == "ask_password":
        USER[chat]["password"] = msg.text.strip()
        USER[chat]["step"] = "login"
        bot.reply_to(msg, "⏳ Logging into Instagram…")
        return login_user(msg)

    # -------- Select GC Step --------
    if USER.get(chat, {}).get("step") == "select_gc":
        try:
            index = int(msg.text.strip()) - 1
            SELECTED_GC[chat] = GC_LIST[chat][index]
            USER[chat]["step"] = "ask_message"
            bot.reply_to(
                msg,
                f"✅ Selected Group: {SELECTED_GC[chat].thread_title}\n\nSend the SPAM message:"
            )
        except:
            bot.reply_to(msg, "❌ Invalid number. Try again.")
        return

    # -------- Ask Message Step --------
    if USER.get(chat, {}).get("step") == "ask_message":
        SPAM[chat] = {"run": True, "text": msg.text}
        USER[chat]["step"] = "spamming"

        bot.reply_to(msg, "🚀 Spam Started!\nSend /stop to stop spam.")

        # Start background looping thread
        threading.Thread(
            target=spam_loop,
            args=(chat,),
            daemon=True
        ).start()

        return


# ---------------------------
# LOGIN USER
# ---------------------------
def login_user(msg):
    chat = msg.chat.id
    cl = Client()

    try:
        cl.login(USER[chat]["username"], USER[chat]["password"])
        USER[chat]["client"] = cl
        bot.reply_to(msg, "✅ Login Successful!\nFetching group chats…")
    except Exception as e:
        bot.reply_to(msg, f"❌ Login Failed:\n`{e}`")
        USER[chat]["step"] = "ask_username"
        return

    threads = cl.direct_threads(amount=60)
    groups = [t for t in threads if t.thread_type == "group"]

    if not groups:
        bot.send_message(chat, "❌ No GC found in this account.")
        USER[chat]["step"] = "ask_username"
        return

    GC_LIST[chat] = groups

    text = "📌 **Your Group Chats:**\n\n"
    for i, g in enumerate(groups):
        text += f"{i+1}. {g.thread_title or 'Unnamed'}\n"

    bot.send_message(chat, text + "\n👉 Send the GC number:")
    USER[chat]["step"] = "select_gc"


# ---------------------------
# SPAM LOOP (24/7)
# ---------------------------
def spam_loop(chat):
    cl = USER[chat]["client"]
    gc = SELECTED_GC[chat]

    while SPAM[chat]["run"]:
        try:
            # Using gc.id (thread_id FIXED)
            cl.direct_send(SPAM[chat]["text"], [gc.id])
            print(f"Sent to {gc.id}")
        except Exception as e:
            print("Spam Error:", e)

        time.sleep(10)   # Anti-ban safe delay


# ---------------------------
# STOP COMMAND
# ---------------------------
@bot.message_handler(commands=['stop'])
def stop(msg):
    chat = msg.chat.id

    if SPAM.get(chat):
        SPAM[chat]["run"] = False
        bot.reply_to(msg, "🛑 Spam Stopped Successfully!")
    else:
        bot.reply_to(msg, "⚠️ No spam is running.")


# ---------------------------
# POLLING
# ---------------------------
bot.polling(non_stop=True, skip_pending=True)
