import telebot
import threading
import time
from instagrapi import Client

# ------------------------
# CONFIG
# ------------------------
BOT_TOKEN = "8054752328:AAHW91DOipkoYVHVZuOBB5VId_DB9OTjRCw"  # Replace this
bot = telebot.TeleBot(BOT_TOKEN)

# ------------------------
# PER USER DATA STORE
# ------------------------
user_sessions = {}   # Telegram user_id → Instagram Client
user_threads = {}    # Telegram user_id → Spam Thread
user_gc = {}          # Telegram user_id → (gc_id, message_to_spam)

# ------------------------
# UTILITY: SEND TYPING EFFECT
# ------------------------
def ig_typing_effect(cl, thread_id, text):
    try:
        cl.direct_send("typing…", thread_ids=[thread_id])
    except:
        pass
    time.sleep(2)
    cl.direct_send(text, thread_ids=[thread_id])


# ------------------------
# SPAM LOOP (runs in background)
# ------------------------
def spam_loop(user_id):
    cl = user_sessions[user_id]
    gc_id, message = user_gc[user_id]

    while True:
        if user_id not in user_threads:  
            break  # stop if user stopped
        try:
            ig_typing_effect(cl, gc_id, message)
        except Exception as e:
            print("Spam error:", e)
        time.sleep(10)  # 10 sec delay


# ------------------------
# COMMAND: /start
# ------------------------
@bot.message_handler(commands=['start'])
def start(message):
    uid = message.from_user.id

    bot.send_chat_action(message.chat.id, "typing")
    bot.reply_to(message,
        "👋 Welcome!\nEnter your Instagram username:"
    )

    bot.register_next_step_handler(message, ask_password)


# ------------------------
# STEP 2: Ask password
# ------------------------
def ask_password(message):
    uid = message.from_user.id
    username = message.text.strip()

    bot.reply_to(message, "🔐 Now send your Instagram password:")
    bot.register_next_step_handler(message, login_user, username)


# ------------------------
# STEP 3: Instagram Login
# ------------------------
def login_user(message, username):
    uid = message.from_user.id
    password = message.text.strip()

    bot.send_chat_action(message.chat.id, "typing")
    bot.reply_to(message, "⏳ Logging in… please wait")

    cl = Client()

    try:
        cl.login(username, password)
        user_sessions[uid] = cl
    except Exception as e:
        bot.reply_to(message, f"❌ Login failed\n{e}")
        return

    # Fetch GCs
    threads = cl.direct_threads()

    if not threads:
        bot.reply_to(message, "❌ No group chats found.")
        return

    gc_list = ""
    for i, t in enumerate(threads):
        gc_list += f"{i}. {t.thread_title}\n"

    bot.reply_to(message, f"👇 Select GC number:\n\n{gc_list}")

    bot.register_next_step_handler(message, select_gc, threads)


# ------------------------
# STEP 4: Select GC
# ------------------------
def select_gc(message, threads):
    uid = message.from_user.id

    if not message.text.isdigit():
        bot.reply_to(message, "❌ Send only number.")
        return

    index = int(message.text)

    if index < 0 or index >= len(threads):
        bot.reply_to(message, "❌ Invalid number.")
        return

    thread = threads[index]
    gc_id = thread.id

    user_gc[uid] = (gc_id, None)

    bot.reply_to(message, "✍️ Send the message you want to spam:")
    bot.register_next_step_handler(message, set_message)


# ------------------------
# STEP 5: Save spam message
# ------------------------
def set_message(message):
    uid = message.from_user.id
    text = message.text

    gc_id, _ = user_gc[uid]
    user_gc[uid] = (gc_id, text)

    bot.reply_to(message, "🚀 Bot started!\nSend /stop to stop.")

    # Start background thread
    t = threading.Thread(target=spam_loop, args=(uid,))
    t.daemon = True
    user_threads[uid] = t
    t.start()


# ------------------------
# COMMAND: /stop
# ------------------------
@bot.message_handler(commands=['stop'])
def stop(message):
    uid = message.from_user.id

    if uid in user_threads:
        del user_threads[uid]
        bot.reply_to(message, "⛔ Bot stopped.")
    else:
        bot.reply_to(message, "Bot was not running.")


# ------------------------
# RUN BOT
# ------------------------
bot.polling(none_stop=True)
