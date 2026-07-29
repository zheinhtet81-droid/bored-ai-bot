import os
import sys
import sqlite3
import logging
import requests
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Standard output ကို UTF-8 ပြောင်းခြင်း
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

# Logging setup
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# Load environment variables
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# Database Initialization
def init_db():
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            birth_date TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def register_user(user_id, username):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)', (user_id, username))
    conn.commit()
    conn.close()

def set_user_birth_date(user_id, birth_date):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET birth_date = ? WHERE user_id = ?', (birth_date, user_id))
    conn.commit()
    conn.close()

def get_user_birth_date(user_id):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('SELECT birth_date FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

# Command Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username)
    
    welcome_text = (
        "👋 မင်္ဂလာပါခင်ဗျာ! **Bored AI** မှ ကြိုဆိုပါတယ်။\n\n"
        "ပိုမိုတိကျသော analysis ရရှိရန် မွေးသက္ကရာဇ်ကို ထည့်သွင်းပေးပါ။\n"
        "(ဥပမာ - `/set_birth_date 2009_03_23`)\n\n"
        "စတင်ကြည့်ရအောင်! 😊"
    )
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def set_birth_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text("ကျေးဇူးပြု၍ မွေးသက္ကရာဇ် ရိုက်ထည့်ပေးပါ။\nဥပမာ - `/set_birth_date 2009_03_23`", parse_mode='Markdown')
        return

    birth_date = context.args[0]
    set_user_birth_date(user_id, birth_date)
    await update.message.reply_text(f"✅ မွေးသက္ကရာဇ် **{birth_date}** ကို သိမ်းဆည်းပြီးပါပြီ!\n\nအကောင့်သစ်အတွက် **10 coins free** ရရှိပါပြီ! 🎉", parse_mode='Markdown')

# Message Handler (Direct Requests to Groq API)
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_text = update.message.text
    birth_date = get_user_birth_date(user_id)

    prompt = f"User Message: {user_text}"
    if birth_date:
        prompt += f"\nUser Birth Date: {birth_date}"

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json; charset=utf-8"
    }

    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {
                "role": "system",
                "content": "You are a helpful AI assistant. Always respond in natural Burmese language."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        "temperature": 0.7
    }

    try:
        url = "https://api.groq.com/openai/v1/chat/completions"
        res = requests.post(url, headers=headers, json=payload, timeout=20)
        data = res.json()

        if res.status_code == 200:
            reply_message = data['choices'][0]['message']['content']
            await update.message.reply_text(reply_message)
        else:
            err_msg = data.get('error', {}).get('message', 'Unknown error')
            await update.message.reply_text(f"🔴 AI Error ({res.status_code}): {err_msg}")

    except Exception as e:
        await update.message.reply_text(f"🔴 Connection Error: {str(e)}")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("set_birth_date", set_birth_date))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
