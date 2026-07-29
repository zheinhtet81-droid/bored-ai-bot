# bot.py
import os
import random
import logging
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from openai import OpenAI
from dotenv import load_dotenv
import sqlite3
from collections import defaultdict
import requests
from bs4 import BeautifulSoup

# --- Load Environment Variables ---
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ADMIN_ID = os.getenv("ADMIN_ID")
CODE_PASSWORD = os.getenv("CODE_PASSWORD")

client = OpenAI(api_key=OPENAI_API_KEY)

# --- Logging Setup ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    filename='bot.log',
    filemode='a'
)
logger = logging.getLogger(__name__)

# --- Database (SQLite) ---
conn = sqlite3.connect('bored_ai.db', check_same_thread=False)
c = conn.cursor()

c.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        birth_date TEXT,
        birth_time TEXT,
        coins INTEGER DEFAULT 10,
        last_coin_recharge DATETIME,
        last_ad_watch DATETIME,
        daily_ad_count INTEGER DEFAULT 0,
        last_ad_reset DATE,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
''')

c.execute('''
    CREATE TABLE IF NOT EXISTS feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        query_type TEXT,
        result_text TEXT,
        rating INTEGER,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
''')

c.execute('''
    CREATE TABLE IF NOT EXISTS activity_stats (
        activity TEXT PRIMARY KEY,
        total_shown INTEGER DEFAULT 0,
        total_liked INTEGER DEFAULT 0,
        total_disliked INTEGER DEFAULT 0,
        last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
    )
''')

c.execute('''
    CREATE TABLE IF NOT EXISTS user_challenges (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        challenge_text TEXT,
        book_name TEXT,
        quiz_question TEXT,
        quiz_answer TEXT,
        completed INTEGER DEFAULT 0,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
''')

conn.commit()

# --- Activity Suggestions (Based on 3-in-1 AI) ---
ACTIVITIES = [
    "၁၀ မိနစ်စာ YouTube tutorial ကြည့်ပါ 🎥",
    "မိမိခန်းမကို သန့်ရှင်းရေးလုပ်ပါ 🧹",
    "စာအုပ်တစ်အုပ် စဖတ်ပါ 📚",
    "မိတ်ဆွေတစ်ယောက်ကို ဖုန်းဆက်ပါ 📞",
    "အိမ်ပြင်ထွက်ပြီး ၁၅ မိနစ် လမ်းလျှောက်ပါ 🚶",
    "ရေခဲမုန့်စားပါ 🍦",
    "ဂီတတစ်ပုဒ် နားထောင်ပါ 🎵",
    "ပုံဆွဲပါ 🎨",
    "ပဟေဠိ (puzzle) ဖြေကြည့်ပါ 🧩",
    "ကိုယ်ကြိုက်တဲ့ ရုပ်ရှင်တစ်ကား ကြည့်ပါ 🎬",
]

MOOD_ACTIVITIES = {
    "bored": ["စိတ်ဝင်စားစရာ podcast နားထောင်ပါ", "အသစ်အသစ်သော ဟင်းချက်နည်းတစ်ခု စမ်းလုပ်ကြည့်ပါ", "ဂိမ်းတစ်ခုခု ဆော့ကြည့်ပါ"],
    "stressed": ["အသက်ရှူလေ့ကျင့်ခန်း ၅ မိနစ် လုပ်ပါ", "တရားထိုင်ပါ", "သီချင်းငြိမ့်ငြိမ့်လေးတွေ နားထောင်ပါ"],
    "happy": ["မိတ်ဆွေတွေနဲ့ အချိန်ဖြုန်းပါ", "ပျော်စရာရုပ်ရှင်ကြည့်ပါ", "ကိုယ်ကြိုက်တာတစ်ခုခု ဝယ်စားပါ"],
    "energetic": ["လေ့ကျင့်ခန်းလုပ်ပါ", "အိမ်ပြင်ထွက်ပြီး လမ်းလျှောက်ပါ", "အသစ်တစ်ခုခု စလေ့လာပါ"],
}

# --- Sponsored Activities (Ads Revenue) ---
SPONSORED_ACTIVITIES = [
    "🎬 Netflix တွင် 'Stranger Things' ကို ကြည့်ပါ (Sponsored) [affiliate_link]",
    "📚 Kindle Unlimited တွင် စာအုပ်အခမဲ့ဖတ်ပါ (Sponsored) [affiliate_link]",
    "🎮 Steam တွင် 'Among Us' ကို ဝယ်ပါ (Sponsored) [affiliate_link]",
]

# --- User Context ---
user_context = {}
user_message_count = defaultdict(int)
RATE_LIMIT = 10  # messages per minute

def check_rate_limit(user_id):
    if user_message_count[user_id] >= RATE_LIMIT:
        return False
    user_message_count[user_id] += 1
    return True

def register_user(user_id, username):
    c.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, username))
    c.execute("UPDATE users SET last_active = CURRENT_TIMESTAMP WHERE user_id = ?", (user_id,))
    conn.commit()

def get_user_coins(user_id):
    c.execute("SELECT coins FROM users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    return result[0] if result else 0

def update_user_coins(user_id, coins):
    c.execute("UPDATE users SET coins = ? WHERE user_id = ?", (coins, user_id))
    conn.commit()

def reset_daily_ad_count(user_id):
    today = datetime.now().date()
    c.execute("SELECT last_ad_reset FROM users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    if result and result[0]:
        last_reset = datetime.strptime(result[0], "%Y-%m-%d").date()
        if last_reset != today:
            c.execute("UPDATE users SET daily_ad_count = 0, last_ad_reset = ? WHERE user_id = ?", (today, user_id))
            conn.commit()
    else:
        c.execute("UPDATE users SET daily_ad_count = 0, last_ad_reset = ? WHERE user_id = ?", (today, user_id))
        conn.commit()

# --- Ad Message (Revenue) ---
def get_ad_message():
    ads = [
        "📢 **Sponsored:** စာအုပ်အခမဲ့ဖတ်ချင်လား? Kindle Unlimited ကို စမ်းသုံးကြည့်ပါ! [affiliate_link]",
        "🎬 **Sponsored:** Netflix တွင် ရုပ်ရှင်အသစ်တွေ ကြည့်လိုက်ပါ! [affiliate_link]",
        "🎮 **Sponsored:** Steam တွင် ဂိမ်းအသစ်တွေ ဝယ်လိုက်ပါ! [affiliate_link]",
        "🛒 **Sponsored:** Lazada/Shopee တွင် ဈေးဝယ်လိုက်ပါ! [affiliate_link]",
    ]
    return random.choice(ads)

# --- Search Engine for Quiz Questions ---
def search_quiz_question(book_name):
    try:
        # Using DuckDuckGo API for search
        query = f"{book_name} book summary quiz questions"
        url = f"https://api.duckduckgo.com/?q={query}&format=json"
        response = requests.get(url)
        data = response.json()
        
        if data.get('AbstractText'):
            question = f"ဤစာအုပ်တွင် ပါဝင်သော အဓိကအကြောင်းအရာမှာ အဘယ်နည်း?"
            answer = data['AbstractText'][:100] + "..."
            return question, answer
        else:
            # Fallback to generic question
            question = f"{book_name} စာအုပ်၏ အဓိကဇာတ်ကောင်မှာ ဘယ်သူလဲ?"
            answer = "စာအုပ်ကို ဖတ်ရှုပြီးမှ သိရှိနိုင်ပါသည်။"
            return question, answer
    except:
        question = f"{book_name} စာအုပ်ကို ဖတ်ရှုပြီးပါသလား?"
        answer = "ဟုတ်ကဲ့"
        return question, answer

# --- Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "Unknown"
    register_user(user_id, username)
    logger.info(f"User {user_id} (@{username}) started the bot")
    
    await update.message.reply_text(
        "👋 မင်္ဂလာပါခင်ဗျာ! **Bored AI** ကို ကြိုဆိုပါတယ်။

"
        "ပိုမိုတိကျသော analysis ရရှိရန် မွေးသက္ကရာဇ်ကို ထည့်သွင်းပေးပါ။

"
        "ဤ bot ကို အသုံးပြုခြင်းအားဖြင့် သင်၏ မွေးသက္ကရာဇ်ကို လုံခြုံစွာ သိမ်းဆည်းထားမည်ဖြစ်ပြီး ဘယ်သူမှ မသိနိုင်ပါ။

"
        "အတုမွေးသက္ကရာဇ်ထည့်ပါက result မှားယွင်းနိုင်ပါသည်။

"
        "Clone account ဖွင့်ပါက result ကွဲသွားနိုင်ပါသည်။

"
        "စတင်ကြည့်ရအောင်! 😊"
    )

async def set_birth_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    birth_date = " ".join(context.args)
    
    c.execute("UPDATE users SET birth_date = ? WHERE user_id = ?", (birth_date, user_id))
    conn.commit()
    
    await update.message.reply_text(f"✅ မွေးသက္ကရာဇ်ကို သိမ်းဆည်းပြီးပါပြီ: {birth_date}

အကောင့်သစ်ဖြစ်သည့်အတွက် **10 coins free** ရရှိပါပြီ! 🎉")
    logger.info(f"User {user_id} set birth date: {birth_date}")

async def set_birth_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    birth_time = " ".join(context.args)
    
    c.execute("UPDATE users SET birth_time = ? WHERE user_id = ?", (birth_time, user_id))
    conn.commit()
    
    await update.message.reply_text(f"✅ မွေးချိန်ကို သိမ်းဆည်းပြီးပါပြီ: {birth_time}")
    logger.info(f"User {user_id} set birth time: {birth_time}")

async def bored(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "Unknown"
    
    if not check_rate_limit(user_id):
        await update.message.reply_text("⚠️ သင်၏ message အရမ်းများနေပါတယ်။ နည်းနည်းနားပြီးမှ ပြန်သုံးပါ။")
        logger.warning(f"Rate limit exceeded for user {user_id}")
        return
    
    register_user(user_id, username)
    
    coins = get_user_coins(user_id)
    if coins < 1:
        await update.message.reply_text("❌ Coin မလောက်ပါ။ ကျေးဇူးပြုပြီး coin ထပ်မံဝယ်ယူပါ သို့မဟုတ် ad ကြည့်ပါ။

1 minute ad ကြည့်ပါက 1 coin ရမည် (တစ်ရက်လျှင် အများဆုံး 5 coins)။")
        return
    
    update_user_coins(user_id, coins - 1)
    
    c.execute("SELECT activity FROM activity_stats ORDER BY (total_liked * 1.0 / total_shown) DESC LIMIT 3")
    top_activities = [row[0] for row in c.fetchall()]
    
    sponsored = random.sample(SPONSORED_ACTIVITIES, 2)
    suggestions = top_activities + sponsored
    
    if len(suggestions) < 5:
        suggestions += random.sample(ACTIVITIES, 5 - len(suggestions))
    
    text = "🎯 **ပျင်းနေရင် ဒီလိုလုပ်ကြည့်ပါ:**

"
    for i, activity in enumerate(suggestions, 1):
        text += f"{i}. {activity}
"
    
    if random.random() < 0.3:
        text += "
" + get_ad_message()
    
    for activity in suggestions:
        c.execute("INSERT INTO activity_stats (activity, total_shown) VALUES (?, 1) ON CONFLICT(activity) DO UPDATE SET total_shown = total_shown + 1, last_updated = CURRENT_TIMESTAMP", (activity,))
    conn.commit()
    
    user_context[user_id] = {"last_activities": suggestions}
    await update.message.reply_text(text)
    logger.info(f"User {user_id} requested /bored")

async def mood(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "Unknown"
    
    if not check_rate_limit(user_id):
        await update.message.reply_text("⚠️ သင်၏ message အရမ်းများနေပါတယ်။ နည်းနည်းနားပြီးမှ ပြန်သုံးပါ။")
        return
    
    register_user(user_id, username)
    
    coins = get_user_coins(user_id)
    if coins < 1:
        await update.message.reply_text("❌ Coin မလောက်ပါ။ ကျေးဇူးပြုပြီး coin ထပ်မံဝယ်ယူပါ သို့မဟုတ် ad ကြည့်ပါ။")
        return
    
    update_user_coins(user_id, coins - 1)
    
    text = "🎭 **မိမိ၏ Mood ကို ရွေးချယ်ပါ:**

"
    text += "/bored — ပျင်းနေတယ်
"
    text += "/stressed — စိတ်ညစ်နေတယ်
"
    text += "/happy — ပျော်နေတယ်
"
    text += "/energetic — တက်ကြွနေတယ်"
    await update.message.reply_text(text)

async def mood_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    mood = update.message.text.lower().replace("/", "")
    if mood in MOOD_ACTIVITIES:
        suggestions = random.sample(MOOD_ACTIVITIES[mood], min(3, len(MOOD_ACTIVITIES[mood])))
        text = f"🌟 **{mood.upper()}** အတွက် အကြံဉာဏ်များ:

"
        for i, activity in enumerate(suggestions, 1):
            text += f"{i}. {activity}
"
        
        if random.random() < 0.2:
            text += "
" + get_ad_message()
        
        await update.message.reply_text(text)
        logger.info(f"User {user_id} requested mood: {mood}")
    else:
        await update.message.reply_text("မသင့်တော်သော mood ဖြစ်နေပါတယ်။ /mood ကို ပြန်ရွေးပါ။")

async def challenge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "Unknown"
    
    if not check_rate_limit(user_id):
        await update.message.reply_text("⚠️ သင်၏ message အရမ်းများနေပါတယ်။ နည်းနည်းနားပြီးမှ ပြန်သုံးပါ။")
        return
    
    register_user(user_id, username)
    
    coins = get_user_coins(user_id)
    if coins < 1:
        await update.message.reply_text("❌ Coin မလောက်ပါ။ ကျေးဇူးပြုပြီး coin ထပ်မံဝယ်ယူပါ သို့မဟုတ် ad ကြည့်ပါ။")
        return
    
    update_user_coins(user_id, coins - 1)
    
    # Get user's birth date for 3-in-1 AI analysis
    c.execute("SELECT birth_date, birth_time FROM users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    birth_date = result[0] if result else "Unknown"
    birth_time = result[1] if result else "Unknown"
    
    # Generate challenge based on 3-in-1 AI result
    challenges = [
        "ယနေ့ စာအုပ် ၁၀ စာမျက်နှာ ဖတ်ပါ 📖",
        "မိသားစုတစ်ယောက်ကို ချစ်ကြောင်းပြောပါ 💖",
        "အိမ်မှာရှိတဲ့ အဝတ်အစားတွေကို စနစ်တကျခေါက်ပါ 👕",
        "၁၅ မိနစ် လေ့ကျင့်ခန်းလုပ်ပါ 💪",
        "မိတ်ဆွေအသစ်တစ်ယောက်နဲ့ စကားပြောကြည့်ပါ 🗣️",
    ]
    daily_challenge = random.choice(challenges)
    
    # Store challenge in database
    c.execute("INSERT INTO user_challenges (user_id, challenge_text) VALUES (?, ?)", (user_id, daily_challenge))
    conn.commit()
    
    text = f"🔥 **နေ့စဉ်စိန်ခေါ်မှု:**

{daily_challenge}

ဒီစိန်ခေါ်မှုကို အောင်မြင်စွာ ပြီးမြောက်အောင်လုပ်ပါ! 💪

ပြီးမြောက်ပါက 'completed' ဟု ရိုက်ပို့ပါ။"
    
    if random.random() < 0.2:
        text += "
" + get_ad_message()
    
    await update.message.reply_text(text)
    logger.info(f"User {user_id} requested /challenge")

async def challenge_completed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message = update.message.text.lower()
    
    if "completed" not in message:
        return
    
    # Get last challenge
    c.execute("SELECT id, challenge_text FROM user_challenges WHERE user_id = ? ORDER BY timestamp DESC LIMIT 1", (user_id,))
    result = c.fetchone()
    
    if not result:
        return
    
    challenge_id, challenge_text = result
    
    # Check if challenge is about reading a book
    if "စာအုပ်" in challenge_text or "book" in challenge_text.lower():
        # Ask for book name
        await update.message.reply_text("📚 ကျေးဇူးပြုပြီး ဖတ်ရှုခဲ့သော စာအုပ်အမည်ကို ရေးသားပေးပါ။")
        user_context[user_id] = {"waiting_for_book": True, "challenge_id": challenge_id}
    else:
        # Mark as completed
        c.execute("UPDATE user_challenges SET completed = 1 WHERE id = ?", (challenge_id,))
        conn.commit()
        await update.message.reply_text("🎉 ဂုဏ်ယူပါတယ်! သင်၏ စိန်ခေါ်မှုကို ပြီးမြောက်စွာ လုပ်ဆောင်နိုင်ခဲ့ပါပြီ။ +1 coin ရရှိပါပြီ! 🪙")
        update_user_coins(user_id, get_user_coins(user_id) + 1)

async def book_name_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    book_name = update.message.text
    
    if user_context.get(user_id, {}).get("waiting_for_book"):
        challenge_id = user_context[user_id]["challenge_id"]
        
        # Search for quiz question
        question, answer = search_quiz_question(book_name)
        
        # Store in database
        c.execute("UPDATE user_challenges SET book_name = ?, quiz_question = ?, quiz_answer = ? WHERE id = ?", (book_name, question, answer, challenge_id))
        conn.commit()
        
        # Ask quiz question
        keyboard = [
            [InlineKeyboardButton("ဟုတ်ကဲ့", callback_data="quiz_yes"),
             InlineKeyboardButton("မဟုတ်ပါ", callback_data="quiz_no")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(f"📖 **မေးခွန်း:**

{question}

ဤမေးခွန်းကို ဖြေဆိုနိုင်ပါသလား?", reply_markup=reply_markup)
        user_context[user_id]["waiting_for_book"] = False

async def quiz_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    query = update.callback_query
    answer = query.data
    
    if answer == "quiz_yes":
        c.execute("UPDATE user_challenges SET completed = 1 WHERE user_id = ? AND completed = 0", (user_id,))
        conn.commit()
        update_user_coins(user_id, get_user_coins(user_id) + 1)
        await query.message.edit_text("🎉 ဂုဏ်ယူပါတယ်! သင်၏ စိန်ခေါ်မှုကို ပြီးမြောက်စွာ လုပ်ဆောင်နိုင်ခဲ့ပါပြီ။ +1 coin ရရှိပါပြီ! 🪙")
    else:
        await query.message.edit_text("❌ စိန်ခေါ်မှုကို ပြန်လည်လုပ်ဆောင်ပါ။ စာအုပ်ကို ဖတ်ရှုပြီးမှ ပြန်လည်ဖြေဆိုနိုင်ပါသည်။")

async def feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "Unknown"
    
    if not check_rate_limit(user_id):
        await update.message.reply_text("⚠️ သင်၏ message အရမ်းများနေပါတယ်။ နည်းနည်းနားပြီးမှ ပြန်သုံးပါ။")
        return
    
    register_user(user_id, username)
    
    last_activities = user_context.get(user_id, {}).get("last_activities", [])
    
    if not last_activities:
        await update.message.reply_text("ပထမ /bored ကို အရင်သုံးပါ၊ ပြီးမှ feedback ပေးပါ။")
        return
    
    text = "💬 **Feedback ပေးပို့ရန်:**

"
    text += "အောက်ပါ activity များထဲမှ မိမိကြိုက်နှစ်သက်ရာကို ရွေးချယ်ပြီး like/dislike ပေးပါ:

"
    for i, activity in enumerate(last_activities, 1):
        text += f"{i}. {activity}
"
    text += "
ဥပမာ: 'like 1' သို့မဟုတ် 'dislike 3' ဟု ရိုက်ပို့ပါ။"
    await update.message.reply_text(text)

async def process_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message = update.message.text.lower()
    
    if not check_rate_limit(user_id):
        return
    
    last_activities = user_context.get(user_id, {}).get("last_activities", [])
    
    if not last_activities:
        return
    
    if "like" in message:
        try:
            index = int(message.split()[-1]) - 1
            if 0 <= index < len(last_activities):
                activity = last_activities[index]
                c.execute("INSERT INTO activity_stats (activity, total_shown, total_liked) VALUES (?, 1, 1) ON CONFLICT(activity) DO UPDATE SET total_shown = total_shown + 1, total_liked = total_liked + 1, last_updated = CURRENT_TIMESTAMP", (activity,))
                c.execute("INSERT INTO feedback (user_id, activity, liked) VALUES (?, ?, 1)", (user_id, activity))
                conn.commit()
                await update.message.reply_text(f"✅ '{activity}' ကို like ပေးသည့်အတွက် ကျေးဇူးတင်ပါတယ်! 🙏")
                logger.info(f"User {user_id} liked activity: {activity}")
            else:
                await update.message.reply_text("❌ မှားယွင်းသော index ဖြစ်နေပါတယ်။")
        except:
            await update.message.reply_text("❌ Feedback format မှားနေပါတယ်။ ဥပမာ: 'like 1'")
    
    elif "dislike" in message:
        try:
            index = int(message.split()[-1]) - 1
            if 0 <= index < len(last_activities):
                activity = last_activities[index]
                c.execute("INSERT INTO activity_stats (activity, total_shown, total_disliked) VALUES (?, 1, 1) ON CONFLICT(activity) DO UPDATE SET total_shown = total_shown + 1, total_disliked = total_disliked + 1, last_updated = CURRENT_TIMESTAMP", (activity,))
                c.execute("INSERT INTO feedback (user_id, activity, liked) VALUES (?, ?, 0)", (user_id, activity))
                conn.commit()
                await update.message.reply_text(f"❌ '{activity}' ကို dislike ပေးသည့်အတွက် ကျေးဇူးတင်ပါတယ်။ ပိုမိုကောင်းမွန်အောင် လုပ်ဆောင်ပါမယ်။ 🙏")
                logger.info(f"User {user_id} disliked activity: {activity}")
            else:
                await update.message.reply_text("❌ မှားယွင်းသော index ဖြစ်နေပါတယ်။")
        except:
            await update.message.reply_text("❌ Feedback format မှားနေပါတယ်။ ဥပမာ: 'dislike 1'")
    else:
        await update.message.reply_text("❌ Feedback format မှားနေပါတယ်။ ဥပမာ: 'like 1' သို့မဟုတ် 'dislike 3'")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if str(user_id) != ADMIN_ID:
        await update.message.reply_text("🔒 ဤ command ကို admin များသာ အသုံးပြုနိုင်ပါတယ်။")
        logger.warning(f"Unauthorized stats access attempt by user {user_id}")
        return
    
    c.execute("SELECT activity, total_shown, total_liked, total_disliked FROM activity_stats ORDER BY total_liked DESC")
    rows = c.fetchall()
    
    text = "📊 **Bot Statistics (Top Activities):**

"
    for i, row in enumerate(rows, 1):
        activity, shown, liked, disliked = row
        approval_rate = (liked / shown * 100) if shown > 0 else 0
        text += f"{i}. {activity}
"
        text += f"   - Shown: {shown}, Liked: {liked}, Disliked: {disliked}, Approval: {approval_rate:.1f}%

"
    
    await update.message.reply_text(text)
    logger.info(f"Admin {user_id} viewed stats")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "ℹ️ **Bored AI Help:**

"
    text += "/start — Bot ကို ပြန်စတင်ရန်
"
    text += "/set_birth_date — မွေးသက္ကရာဇ် ထည့်သွင်းရန်
"
    text += "/set_birth_time — မွေးချိန် ထည့်သွင်းရန် (optional)
"
    text += "/bored — ပျင်းနေလို့ ဘာလုပ်ရမလဲ
"
    text += "/mood — Mood အလိုက် အကြံဉာဏ်
"
    text += "/challenge — နေ့စဉ်စိန်ခေါ်မှု
"
    text += "/feedback — Feedback ပေးပို့ရန်
"
    text += "/stats — Bot statistics (admin only)
"
    text += "/help — ဤအကူအညီ

"
    text += "မေးခွန်းရှိရင် developer ကို ဆက်သွယ်နိုင်ပါတယ်။ 🙏"
    await update.message.reply_text(text)

async def ai_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "Unknown"
    user_message = update.message.text
    
    if not check_rate_limit(user_id):
        await update.message.reply_text("⚠️ သင်၏ message အရမ်းများနေပါတယ်။ နည်းနည်းနားပြီးမှ ပြန်သုံးပါ။")
        logger.warning(f"Rate limit exceeded for user {user_id}")
        return
    
    register_user(user_id, username)
    
    if len(user_message) > 500:
        await update.message.reply_text("⚠️ Message အရမ်းရှည်နေပါတယ်။ ၅၀၀ စာလုံးအောက်သာ ရိုက်ပါ။")
        logger.warning(f"User {user_id} sent too long message")
        return
    
    coins = get_user_coins(user_id)
    if coins < 1:
        await update.message.reply_text("❌ Coin မလောက်ပါ။ ကျေးဇူးပြုပြီး coin ထပ်မံဝယ်ယူပါ သို့မဟုတ် ad ကြည့်ပါ။")
        return
    
    update_user_coins(user_id, coins - 1)
    
    c.execute("SELECT activity FROM activity_stats ORDER BY (total_liked * 1.0 / total_shown) DESC LIMIT 3")
    top_activities = [row[0] for row in c.fetchall()]
    
    prompt = f"""
    You are Bored AI, an expert in Vedic & Western Astrology, Numerology, and Personality Psychology.
    
    Based on the user's message, suggest 3-5 fun, productive, or relaxing activities.
    Use Myanmar language (Unicode).
    
    Top activities (from user feedback): {top_activities}
    
    User message: {user_message}
    
    Your response (in Myanmar language, short and friendly):
    """
    
    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
            temperature=0.7
        )
        ai_text = response.choices[0].message.content.strip()
        await update.message.reply_text(f"🤖 **Bored AI:**

{ai_text}")
        logger.info(f"User {user_id} used AI: {user_message[:50]}...")
    except Exception as e:
        await update.message.reply_text(f"🔴 AI error: {str(e)}")
        logger.error(f"AI error for user {user_id}: {str(e)}")

# --- Main ---
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("set_birth_date", set_birth_date))
    app.add_handler(CommandHandler("set_birth_time", set_birth_time))
    app.add_handler(CommandHandler("bored", bored))
    app.add_handler(CommandHandler("mood", mood))
    app.add_handler(CommandHandler("challenge", challenge))
    app.add_handler(CommandHandler("feedback", feedback))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("help", help_command))
    
    app.add_handler(CommandHandler("stressed", lambda u, c: mood_response(u, c)))
    app.add_handler(CommandHandler("happy", lambda u, c: mood_response(u, c)))
    app.add_handler(CommandHandler("energetic", lambda u, c: mood_response(u, c)))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_feedback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ai_response))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, challenge_completed))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, book_name_received))
    app.add_handler(CallbackQueryHandler(quiz_callback))
    
    logger.info("Bot started successfully")
    app.run_polling()

if __name__ == "__main__":
    main()
