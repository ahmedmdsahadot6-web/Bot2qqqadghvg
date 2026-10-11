import os
import asyncio
import logging
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
from pymongo import MongoClient

# লগিং সেটআপ
logging.basicConfig(level=logging.INFO)

# এনভায়রনমেন্ট ভ্যারিয়েবল থেকে কনফিগারেশন লোড করা
API_ID = int(os.getenv("API_ID", "37903178"))  # আপনার my.telegram.org এর API_ID
API_HASH = os.getenv("API_HASH", "b4d288715cf8dee6c2b048d5c94881e3")
BOT_TOKEN = os.getenv("BOT_TOKEN", "8869783838:AAFyPZC1qLvHo0cO_hWUKfgE1ERxgIUTvd8")
MONGO_URI = os.getenv("MONGO_URI", "your_mongodb_uri")

# ডাটাবেস কানেকশন
mongo_client = MongoClient(MONGO_URI)
db = mongo_client["telegram_voice_bot"]
users_collection = db["users"]

# বটের ক্লায়েন্ট ইনিশিয়ালাইজেশন
app = Client("voice_control_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# --- 1. টেলিগ্রাম বট ইন্টারফেস (Bot Handlers) ---

@app.on_message(filters.command("start"))
async def start_command(client, message: Message):
    user_id = message.from_user.id
    if not users_collection.find_one({"user_id": user_id}):
        users_collection.insert_one({
            "user_id": user_id,
            "session_string": None,
            "target_channel": None,
            "live_channel": None,
            "is_active": False
        })
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔑 Login (String Session)", callback_data="set_session")],
        [InlineKeyboardButton("🎯 Target Channel", callback_data="set_target")],
        [InlineKeyboardButton("📺 Live Stream Channel", callback_data="set_live")],
        [InlineKeyboardButton("📊 Live Status", callback_data="status")],
        [InlineKeyboardButton("ℹ️ Help", callback_data="help")]
    ])
    
    await message.reply_text(
        "👋 **স্বাগতম!** এটি লাইভ স্ট্রিম অটো-আনমিউট বট।\nনিচের মেনু থেকে আপনার সেটিংস কনফিগার করুন:",
        reply_markup=keyboard
    )

@app.on_callback_query()
async def callback_handler(client, callback_query: CallbackQuery):
    data = callback_query.data
    user_id = callback_query.from_user.id

    if data == "set_session":
        await callback_query.message.edit_text(
            "🔑 আপনার Pyrogram String Session দিন।\n(সতর্কতা: এটি গোপনীয়, নিজস্ব দায়িত্বে প্রদান করুন)।"
        )
    elif data == "set_target":
        await callback_query.message.edit_text("🎯 আপনার টার্গেট চ্যানেলের ইউজারনেম দিন (যেমন: @MyTargetChannel):")
    elif data == "set_live":
        await callback_query.message.edit_text("📺 আপনার লাইভ স্ট্রিম চ্যানেলের ইউজারনেম দিন (যেমন: @MyLiveChannel):")
    elif data == "status":
        user_data = users_collection.find_one({"user_id": user_id}) or {}
        status_text = (
            f"📊 **আপনার লাইভ স্ট্যাটাস:**\n\n"
            f"• টার্গেট চ্যানেল: {user_data.get('target_channel', 'সেট করা হয়নি')}\n"
            f"• লাইভ চ্যানেল: {user_data.get('live_channel', 'সেট করা হয়নি')}\n"
            f"• বট সচল আছে?: {'হ্যাঁ ✅' if user_data.get('is_active') else 'না ❌'}"
        )
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back_home")]])
        await callback_query.message.edit_text(status_text, reply_markup=keyboard)
    elif data == "help":
        help_text = (
            "ℹ️ **সাহায্যিকা / গাইড:**\n\n"
            "১. প্রথমে আপনার ইউজার অ্যাকাউন্ট দিয়ে String Session যুক্ত করুন।\n"
            "২. টার্গেট চ্যানেল ও লাইভ স্ট্রিম চ্যানেল সেট করুন।\n"
            "৩. লাইভ শুরু হলে বট স্বয়ংক্রিয়ভাবে টার্গেট মেম্বারদের আনমিউট করবে।"
        )
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back_home")]])
        await callback_query.message.edit_text(help_text, reply_markup=keyboard)
    elif data == "back_home":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔑 Login (String Session)", callback_data="set_session")],
            [InlineKeyboardButton("🎯 Target Channel", callback_data="set_target")],
            [InlineKeyboardButton("📺 Live Stream Channel", callback_data="set_live")],
            [InlineKeyboardButton("📊 Live Status", callback_data="status")],
            [InlineKeyboardButton("ℹ️ Help", callback_data="help")]
        ])
        await callback_query.message.edit_text("প্রধান মেনুতে ফিরে এসেছেন:", reply_markup=keyboard)

# --- 2. ব্যাকগ্রাউন্ড ওয়ার্কার (Background Monitor & Auto-Unmute Engine) ---

async def background_worker():
    logging.info("Background worker started...")
    while True:
        try:
            active_users = users_collection.find({"is_active": True})
            for user_data in active_users:
                session_string = user_data.get("session_string")
                target_channel = user_data.get("target_channel")
                live_channel = user_data.get("live_channel")

                if not session_string or not target_channel or not live_channel:
                    continue

                # ইউজারের নিজস্ব ইউজারবট সেশন দিয়ে লাইভ চ্যানেল মনিটর করার লজিক
                try:
                    async with Client(f"user_{user_data['user_id']}", api_id=API_ID, api_hash=API_HASH, session_string=session_string) as userbot:
                        # লাইভ ভয়েস চ্যাট বা মেম্বার মনিটরিং প্রসেস এখানে কাজ করবে
                        logging.info(f"Checking live stream for user {user_data['user_id']} in {live_channel}")
                except Exception as e:
                    logging.error(f"Userbot error for user {user_data['user_id']}: {e}")

        except Exception as e:
            logging.error(f"Worker loop error: {e}")
        
        # প্রতি ১০ সেকেন্ড পর পর চেক করবে
        await asyncio.sleep(10)

# --- 3. একসাথে রান করার মেইন ফাংশন ---

async def main():
    # বট স্টার্ট করা
    await app.start()
    logging.info("Telegram Bot started successfully!")
    
    # ব্যাকগ্রাউন্ড ওয়ার্কার রান করা
    asyncio.create_task(background_worker())
    
    # বট যেন বন্ধ না হয়ে সচল থাকে
    await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
