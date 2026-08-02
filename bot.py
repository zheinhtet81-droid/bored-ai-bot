import os
import sys
import sqlite3
import logging
import requests
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Standard output encoding setup
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
            birth_date TEXT,
            language TEXT DEFAULT 'Burmese'
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def register_user(user_id, username):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO users (user_id, username, language) VALUES (?, ?, ?)', (user_id, username, 'Burmese'))
    conn.commit()
    conn.close()

def set_user_birth_date(user_id, birth_date):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET birth_date = ? WHERE user_id = ?', (birth_date, user_id))
    conn.commit()
    conn.close()

def set_user_language(user_id, lang):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET language = ? WHERE user_id = ?', (lang, user_id))
    conn.commit()
    conn.close()

def get_user_info(user_id):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('SELECT birth_date, language FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    if result:
        return {"birth_date": result[0], "language": result[1]}
    return {"birth_date": None, "language": "Burmese"}

# Command Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username)
    
    welcome_text = (
        "👋 မင်္ဂလာပါ! **AstroOracle AI** မှ ကြိုဆိုပါတယ်။\n\n"
        "🌐 **၁။ ဘာသာစကား ပြောင်းရန် / Set Language:**\n"
        "`/lang English` သို့မဟုတ် `/lang Burmese` သို့မဟုတ် `/lang Thai`\n\n"
        "📅 **၂။ မွေးသက္ကရာဇ် ထည့်ရန် / Set Birth Date:**\n"
        "(ဥပမာ - `/set_birth_date 2005_03_23`)\n\n"
        "🔮 မွေးသက္ကရာဇ် ထည့်ပြီးပါက သိလိုသမျှ မေးမြန်းနိုင်ပြီး **ဟောကိန်းများအပြင် ဆောင်ရန်/ရှောင်ရန် အဆောင်အယောင်နှင့် ယတြာများပါ** တွက်ချက်ပေးပါမည်!"
    )
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def set_lang(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text("ကျေးဇူးပြု၍ ဘာသာစကား ရွေးချယ်ပေးပါ။\nExample: `/lang English` or `/lang Burmese` or `/lang Thai`", parse_mode='Markdown')
        return

    lang = context.args[0].capitalize()
    set_user_language(user_id, lang)
    await update.message.reply_text(f"✅ Main Preferred Language set to: **{lang}**", parse_mode='Markdown')

async def set_birth_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text("ကျေးဇူးပြု၍ မွေးသက္ကရာဇ် ရိုက်ထည့်ပေးပါ။\nဥပမာ - `/set_birth_date 2005_03_23`", parse_mode='Markdown')
        return

    birth_date = context.args[0]
    set_user_birth_date(user_id, birth_date)
    await update.message.reply_text(f"✅ မွေးသက္ကရာဇ် **{birth_date}** ကို မှတ်သားလိုက်ပါပြီ!", parse_mode='Markdown')

# Message Handler
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_text = update.message.text
    user_info = get_user_info(user_id)

    birth_date = user_info.get("birth_date")
    preferred_lang = user_info.get("language", "Burmese")

    system_prompt = (
        "You are 'AstroOracle AI', a master astrologer in Myanmar Mahabote, Numerology, Western Zodiac, and Tarot. "
        "Analyze the user's situation using astrological logic. "
        "IMPORTANT RULES:\n"
        "1. Provide detailed astrological predictions.\n"
        "2. ALWAYS suggest specific remedies (ယတြာ), lucky colors, gemstones, and recommended amulets/charms (အဆောင်အယောင်).\n"
        f"3. Respond fluently, naturally, and politely in the user's preferred language: '{preferred_lang}'."
    )

    user_payload_prompt = f"User Question: {user_text}\nPreferred Response Language: {preferred_lang}"
    if birth_date:
        user_payload_prompt += f"\nUser Birth Date: {birth_date}"
    else:
        user_payload_prompt += "\nNote: User has not set a birth date. Kindly remind them to use /set_birth_date for deeper accuracy."

    clean_api_key = GROQ_API_KEY.strip() if GROQ_API_KEY else ""

    headers = {
        "Authorization": f"Bearer {clean_api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": user_payload_prompt
            }
        ],
        "temperature": 0.6
    }

    try:
        url = "https://api.groq.com/openai/v1/chat/completions"
        res = requests.post(url, headers=headers, json=payload, timeout=25)
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
    app.add_handler(CommandHandler("lang", set_lang))
    app.add_handler(CommandHandler("set_birth_date", set_birth_date))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("AstroOracle Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
