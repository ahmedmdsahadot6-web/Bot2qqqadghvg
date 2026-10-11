import os
import io
import time
import asyncio
import logging
import sqlite3

from dotenv import load_dotenv
from aiohttp import web

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BufferedInputFile,
    ReplyKeyboardMarkup,
    KeyboardButton
)
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from telethon import TelegramClient, functions, types
from telethon.sessions import StringSession
from telethon.errors import (
    RPCError,
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    PasswordHashInvalidError,
    PhoneCodeExpiredError
)

import qrcode

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "8869783838:AAFyPZC1qLvHo0cO_hWUKfgE1ERxgIUTvd8").strip()
API_HASH = os.getenv("API_HASH", "b4d288715cf8dee6c2b048d5c94881e3").strip()

try:
    API_ID = int(os.getenv("API_ID", "0"))
except ValueError:
    API_ID = 0

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN missing")

if not API_ID:
    raise RuntimeError("API_ID missing")

if not API_HASH:
    raise RuntimeError("API_HASH missing")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger("AutoSpeakerBot")

DB_FILE = "speaker_manager.db"
db = sqlite3.connect(DB_FILE, check_same_thread=False)
db.row_factory = sqlite3.Row

def init_db():
    db.execute("""  
        CREATE TABLE IF NOT EXISTS users (  
            user_id INTEGER PRIMARY KEY,  
            session_string TEXT,  
            connected INTEGER DEFAULT 0,  
            created_at INTEGER  
        )  
    """)  

    db.execute("""  
        CREATE TABLE IF NOT EXISTS channels (  
            id INTEGER PRIMARY KEY AUTOINCREMENT,  
            owner_id INTEGER NOT NULL,  
            channel_type TEXT NOT NULL,  
            channel_username TEXT NOT NULL,  
            channel_id INTEGER,  
            title TEXT,  
            active INTEGER DEFAULT 1,  
            auto_allow INTEGER DEFAULT 1,  
            created_at INTEGER,  
            UNIQUE(owner_id, channel_type)  
        )  
    """)  
    db.commit()

init_db()

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

clients = {}
phone_login_data = {}
temp_login_clients = {}

def get_client(user_id):
    if user_id not in clients:
        row = db.execute("SELECT session_string FROM users WHERE user_id=? AND connected=1", (user_id,)).fetchone()
        session_str = row["session_string"] if row else ""
        
        clients[user_id] = TelegramClient(
            StringSession(session_str),
            API_ID,
            API_HASH,
            device_model="PC 64bit",
            system_version="Windows 11",
            app_version="4.8.1 x64",
            lang_code="en",
            system_lang_code="en-US",
            connection_retries=5,
            timeout=30
        )
    return clients[user_id]

class TargetChannelState(StatesGroup):
    waiting_channel = State()

class LiveChannelState(StatesGroup):
    waiting_channel = State()

class PhoneLoginState(StatesGroup):
    waiting_phone = State()
    waiting_code = State()
    waiting_password = State()

def main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="🔐 Connect Telegram"),
                KeyboardButton(text="🎯 Target Channel")
            ],
            [
                KeyboardButton(text="📺 Live Stream Channel"),
                KeyboardButton(text="📊 Live Status")
            ],
            [
                KeyboardButton(text="ℹ️ Help")
            ]
        ],
        resize_keyboard=True,
        is_persistent=True
    )

def main_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔐 Connect Telegram", callback_data="connect")],
            [InlineKeyboardButton(text="🎯 Target Channel", callback_data="target")],
            [InlineKeyboardButton(text="📺 Live Stream Channel", callback_data="live")],
            [InlineKeyboardButton(text="📊 Live Status", callback_data="status")],
            [InlineKeyboardButton(text="ℹ Help", callback_data="help")]
        ]
    )

@router.message(CommandStart())
async def start_handler(message: Message):
    await message.answer(  
        "🎙 <b>TELEGRAM AUTO SPEAKER</b>\n\n"  
        "Target Channel-এর সদস্যরা Live Stream Channel-এর Live-এ join করলে তাদের speaking permission দেওয়ার কাজ করবে।\n\n"  
        "প্রথমে নিচের থেকে 🔐 Connect Telegram করুন।",  
        parse_mode="HTML",  
        reply_markup=main_keyboard()  
    )  
    await message.answer(  
        "👇 Control Panel:",  
        reply_markup=main_menu()  
    )

async def send_help(message):
    await message.answer(  
        "ℹ️ <b>কিভাবে কাজ করবে</b>\n\n"  
        "1️⃣ 🔐 Connect Telegram করুন (Phone Number দিয়ে String Session তৈরি)\n\n"  
        "2️⃣ 🎯 Target Channel সেট করুন (যাদের পারমিশন দিতে চান)\n\n"  
        "3️⃣ 📺 Live Stream Channel সেট করুন (যেখানে লাইভ চলবে)\n\n"  
        "4️⃣ Target Channel-এর কোনো সদস্য Live-এ join করলে Bot তাকে অটো আনমিউট করবে।",  
        parse_mode="HTML",  
        reply_markup=main_keyboard()  
    )

@router.message(F.text == "ℹ️ Help")
async def help_text_handler(message: Message):
    await send_help(message)

@router.callback_query(F.data == "help")
async def help_callback(call: CallbackQuery):
    await call.answer()  
    await send_help(call.message)

@router.message(F.text == "🔐 Connect Telegram")
async def connect_text_handler(message: Message, state: FSMContext):
    await connect_telegram_menu(message, state)

@router.callback_query(F.data == "connect")
async def connect_callback(call: CallbackQuery, state: FSMContext):
    await call.answer()  
    await connect_telegram_menu(call.message, state)

async def connect_telegram_menu(message: Message, state: FSMContext):
    user_id = message.chat.id  
    row = db.execute("SELECT connected FROM users WHERE user_id=?", (user_id,)).fetchone()
    
    if row and row["connected"] == 1:
        await message.answer(  
            "✅ <b>Telegram Already Connected</b>\n\n"  
            "আপনার অ্যাকাউন্ট ইতিমধ্যে কানেক্টেড আছে। এখন Target ও Live Channel সেট করুন।",  
            parse_mode="HTML",  
            reply_markup=main_keyboard()  
        )  
        return  

    await state.set_state(PhoneLoginState.waiting_phone)
    await message.answer(
        "📱 <b>Telegram Login via Phone Number</b>\n\n"
        "আপনার টেলিগ্রাম অ্যাকাউন্টের ফোন নম্বরটি কান্ট্রি কোডসহ পাঠান (যেমন: <code>+8801712345678</code>):",
        parse_mode="HTML"
    )

@router.message(PhoneLoginState.waiting_phone)
async def process_phone_number(message: Message, state: FSMContext):
    phone = message.text.strip()
    user_id = message.chat.id

    try:
        client = TelegramClient(StringSession(), API_ID, API_HASH, connection_retries=5)
        await client.connect()
        temp_login_clients[user_id] = client

        sent_code = await client.send_code_request(phone)
        
        phone_login_data[user_id] = {
            "phone": phone,
            "phone_code_hash": sent_code.phone_code_hash
        }

        await state.set_state(PhoneLoginState.waiting_code)
        await message.answer(
            "📩 আপনার টেলিগ্রাম অ্যাপে একটি ওটিপি (OTP) কোড পাঠানো হয়েছে।\n"
            "কোডটি এখানে দিন (যেমন: <code>12345</code>):",
            parse_mode="HTML"
        )

    except PhoneNumberInvalidError:
        await message.answer("❌ ফোন নম্বরটি সঠিক নয়। সঠিক ফরম্যাটে আবার দিন (যেমন: <code>+8801712345678</code>):", parse_mode="HTML")
    except Exception as e:
        logger.exception(e)
        await message.answer(f"❌ কোড পাঠানো যায়নি: {e}")
        await state.clear()

@router.message(PhoneLoginState.waiting_code)
async def process_phone_code(message: Message, state: FSMContext):
    code = message.text.strip().replace(" ", "")
    user_id = message.chat.id
    client = temp_login_clients.get(user_id)
    data = phone_login_data.get(user_id)

    if not client or not data:
        await message.answer("❌ সেশন মেয়াদোত্তীর্ণ হয়েছে। আবার চেষ্টা করুন।", reply_markup=main_keyboard())
        await state.clear()
        return

    try:
        await client.sign_in(
            phone=data["phone"],
            code=code,
            phone_code_hash=data["phone_code_hash"]
        )

        session_string = client.session.save()
        await client.disconnect()

        db.execute(
            """  
            INSERT OR REPLACE INTO users  
            (user_id, session_string, connected, created_at)  
            VALUES (?, ?, 1, ?)  
            """,
            (user_id, session_string, int(time.time()))
        )
        db.commit()
        
        if user_id in clients:
            clients.pop(user_id, None)

        await state.clear()
        phone_login_data.pop(user_id, None)
        temp_login_clients.pop(user_id, None)

        await message.answer(
            "✅ <b>Telegram Connected Successfully!</b>\n\n"
            "এখন Target ও Live Channel সেট করুন।",
            parse_mode="HTML",
            reply_markup=main_keyboard()
        )

    except SessionPasswordNeededError:
        await state.set_state(PhoneLoginState.waiting_password)
        await message.answer(
            "🔐 আপনার অ্যাকাউন্টে <b>2-Step Verification (2FA)</b> চালু আছে।\n\n"
            "দয়া করে আপনার ক্লাউড পাসওয়ার্ডটি এখানে পাঠান:",
            parse_mode="HTML"
        )
    except (PhoneCodeInvalidError, PhoneCodeExpiredError):
        await message.answer("❌ কোডটি ভুল বা মেয়াদোত্তীর্ণ। সঠিক কোডটি আবার দিন:")
    except Exception as e:
        logger.exception(e)
        await message.answer(f"❌ লগইন ব্যর্থ হয়েছে: {e}", reply_markup=main_keyboard())
        await state.clear()

@router.message(PhoneLoginState.waiting_password)
async def process_2fa_password(message: Message, state: FSMContext):
    password = message.text.strip()
    user_id = message.chat.id
    client = temp_login_clients.get(user_id)

    if not client:
        await message.answer("❌ সেশন বাতিল হয়েছে। আবার চেষ্টা করুন।", reply_markup=main_keyboard())
        await state.clear()
        return

    try:
        await client.sign_in(password=password)
        session_string = client.session.save()
        await client.disconnect()

        db.execute(
            """  
            INSERT OR REPLACE INTO users  
            (user_id, session_string, connected, created_at)  
            VALUES (?, ?, 1, ?)  
            """,
            (user_id, session_string, int(time.time()))
        )
        db.commit()
        
        if user_id in clients:
            clients.pop(user_id, None)

        await state.clear()
        phone_login_data.pop(user_id, None)
        temp_login_clients.pop(user_id, None)

        await message.answer(
            "✅ <b>2FA পাসওয়ার্ড দিয়ে Telegram Connected!</b>\n\n"
            "এখন Target ও Live Channel সেট করুন।",
            parse_mode="HTML",
            reply_markup=main_keyboard()
        )

    except PasswordHashInvalidError:
        await message.answer("❌ 2FA পাসওয়ার্ড ভুল হয়েছে। সঠিক পাসওয়ার্ডটি আবার দিন:")
    except Exception as e:
        logger.exception(e)
        await message.answer(f"❌ লগইন সম্পন্ন করা যায়নি: {e}", reply_markup=main_keyboard())
        await state.clear()

def is_connected_user(user_id):
    row = db.execute("SELECT connected FROM users WHERE user_id=?", (user_id,)).fetchone()  
    return bool(row and row["connected"])

@router.message(F.text == "🎯 Target Channel")
async def target_text_handler(message: Message, state: FSMContext):
    await target_start(message, state)

@router.callback_query(F.data == "target")
async def target_callback(call: CallbackQuery, state: FSMContext):
    await call.answer()  
    await target_start(call.message, state)

async def target_start(message, state):
    user_id = message.chat.id  
    if not is_connected_user(user_id):  
        await message.answer("❌ আগে 🔐 Connect Telegram করুন।")  
        return  

    old = db.execute("SELECT * FROM channels WHERE owner_id=? AND channel_type='target' AND active=1", (user_id,)).fetchone()  

    if old:  
        await message.answer(  
            "🎯 <b>Target Channel</b>\n\n"  
            f"📺 {old['title']}\n"  
            f"🔗 {old['channel_username']}\n\n"  
            "পরিবর্তন করতে নতুন @username পাঠান।",  
            parse_mode="HTML"  
        )  
    else:  
        await message.answer(  
            "🎯 <b>Target Channel</b>\n\n"  
            "যে Channel-এর সদস্যদের Allow to Speak করতে চান তার username পাঠান (যেমন: <code>@MyTargetChannel</code>):",  
            parse_mode="HTML"  
        )  

    await state.set_state(TargetChannelState.waiting_channel)

@router.message(TargetChannelState.waiting_channel)
async def save_target_channel(message: Message, state: FSMContext):
    await save_channel(message, state, "target")

@router.message(F.text == "📺 Live Stream Channel")
async def live_text_handler(message: Message, state: FSMContext):
    await live_start(message, state)

@router.callback_query(F.data == "live")
async def live_callback(call: CallbackQuery, state: FSMContext):
    await call.answer()  
    await live_start(call.message, state)

async def live_start(message, state):
    user_id = message.chat.id  
    if not is_connected_user(user_id):  
        await message.answer("❌ আগে 🔐 Connect Telegram করুন।")  
        return  

    old = db.execute("SELECT * FROM channels WHERE owner_id=? AND channel_type='live' AND active=1", (user_id,)).fetchone()  

    if old:  
        await message.answer(  
            "📺 <b>Live Stream Channel</b>\n\n"  
            f"📺 {old['title']}\n"  
            f"🔗 {old['channel_username']}\n\n"  
            "পরিবর্তন করতে নতুন @username পাঠান।",  
            parse_mode="HTML"  
        )  
    else:  
        await message.answer(  
            "📺 <b>Live Stream Channel</b>\n\n"  
            "যে Channel-এ Telegram Live চলবে তার username পাঠান (যেমন: <code>@MyLiveChannel</code>):",  
            parse_mode="HTML"  
        )  

    await state.set_state(LiveChannelState.waiting_channel)

@router.message(LiveChannelState.waiting_channel)
async def save_live_channel(message: Message, state: FSMContext):
    await save_channel(message, state, "live")

async def save_channel(message, state, channel_type):
    username = (message.text or "").strip()  
    if not username:  
        await message.answer("❌ Channel username দিন।")  
        return  

    if not username.startswith("@"):  
        username = "@" + username  

    user_id = message.from_user.id  
    client = get_client(user_id)  

    try:  
        if not client.is_connected():
            await client.connect()
            
        entity = await client.get_entity(username)  
        title = getattr(entity, "title", username)  

        db.execute(  
            """  
            INSERT INTO channels  
            (owner_id, channel_type, channel_username, channel_id, title, active, auto_allow, created_at)  
            VALUES (?, ?, ?, ?, ?, 1, 1, ?)  
            ON CONFLICT(owner_id, channel_type)  
            DO UPDATE SET  
                channel_username=excluded.channel_username,  
                channel_id=excluded.channel_id,  
                title=excluded.title,  
                active=1,  
                created_at=excluded.created_at  
            """,  
            (user_id, channel_type, username, entity.id, title, int(time.time()))  
        )  
        db.commit()  
        await state.clear()  

        await message.answer(  
            f"✅ <b>{channel_type.capitalize()} Channel Added</b>\n\n"  
            f"📺 {title}\n"  
            f"🔗 {username}",  
            parse_mode="HTML",  
            reply_markup=main_keyboard()  
        )  

    except Exception as e:  
        logger.exception(e)  
        await message.answer(f"❌ Channel add করা যায়নি: {e}")  
        await state.clear()

def get_channel(owner_id, channel_type):
    return db.execute("SELECT * FROM channels WHERE owner_id=? AND channel_type=? AND active=1", (owner_id, channel_type)).fetchone()

async def get_active_call(client, channel_username):
    entity = await client.get_entity(channel_username)  
    full = await client(functions.channels.GetFullChannelRequest(channel=entity))  
    call = getattr(full.full_chat, "call", None)  
    return call, entity

async def get_participants(client, call):
    input_call = types.InputGroupCall(id=call.id, access_hash=call.access_hash)  
    result = await client(functions.phone.GetGroupCallRequest(call=input_call, limit=100, offset=0))  
    users = {user.id: user for user in result.users}  
    return result.participants, users

async def is_target_member(client, target_entity, user):
    try:  
        participant = await client(  
            functions.channels.GetParticipantRequest(  
                channel=target_entity,  
                participant=types.InputPeerUser(user_id=user.id, access_hash=user.access_hash)  
            )  
        )  
        member = participant.participant  
        if isinstance(member, (types.ChannelParticipantLeft, types.ChannelParticipantBanned)):  
            return False  
        return True  
    except Exception:  
        return False

async def allow_participant(client, call, user):
    input_call = types.InputGroupCall(id=call.id, access_hash=call.access_hash)  
    participant = await client.get_input_entity(user)  
    await client(  
        functions.phone.EditGroupCallParticipantRequest(  
            call=input_call,  
            participant=participant,  
            muted=False  
        )  
    )

async def monitor_user(user_id):
    target_row = get_channel(user_id, "target")  
    live_row = get_channel(user_id, "live")  

    if not target_row or not live_row:  
        return  

    client = get_client(user_id)  

    try:  
        if not client.is_connected():  
            await client.connect()  

        call, live_entity = await get_active_call(client, live_row["channel_username"])  
        if not call:  
            return  

        target_entity = await client.get_entity(target_row["channel_username"])  
        participants, users = await get_participants(client, call)  

        for participant in participants:  
            peer = participant.peer  
            if not isinstance(peer, types.PeerUser):  
                continue  

            user = users.get(peer.user_id)  
            if not user:  
                continue  

            member = await is_target_member(client, target_entity, user)  
            if not member:  
                continue  

            muted = getattr(participant, "muted", False)  
            if not muted:  
                continue  

            try:  
                await allow_participant(client, call, user)  
                logger.info("Target member allowed: %s in live %s", user.id, live_row["channel_username"])  
            except Exception as e:  
                logger.warning("Allow participant failed: %s", e)  

            await asyncio.sleep(0.15)  

    except Exception as e:  
        logger.warning("Monitor error user=%s: %s", user_id, e)

async def auto_monitor():
    logger.info("Auto Speaker Monitor Started")  
    while True:  
        try:  
            rows = db.execute("SELECT DISTINCT owner_id FROM channels WHERE active=1").fetchall()  
            for row in rows:  
                try:  
                    await monitor_user(row["owner_id"])  
                except Exception:  
                    pass  
                await asyncio.sleep(0.5)  
        except Exception:  
            pass  
        await asyncio.sleep(3)

@router.message(F.text == "📊 Live Status")
async def status_text_handler(message: Message):
    await live_status_message(message)

@router.callback_query(F.data == "status")
async def status_callback(call: CallbackQuery):
    await call.answer()  
    await live_status_message(call.message)

async def live_status_message(message):
    user_id = message.chat.id  
    target_row = get_channel(user_id, "target")  
    live_row = get_channel(user_id, "live")  

    if not target_row or not live_row:  
        await message.answer("❌ Target অথবা Live Channel সেট করা হয়নি।")  
        return  

    client = get_client(user_id)  

    try:  
        if not client.is_connected():
            await client.connect()  
            
        call, live_entity = await get_active_call(client, live_row["channel_username"])  

        if not call:  
            await message.answer("🔴 <b>LIVE OFFLINE</b>", parse_mode="HTML")  
            return  

        participants, users = await get_participants(client, call)  
        target_entity = await client.get_entity(target_row["channel_username"])  

        members, muted, allowed = 0, 0, 0  

        for participant in participants:  
            peer = participant.peer  
            if not isinstance(peer, types.PeerUser):  
                continue  
            user = users.get(peer.user_id)  
            if not user:  
                continue  

            if await is_target_member(client, target_entity, user):  
                members += 1  
                if getattr(participant, "muted", False):  
                    muted += 1  
                else:  
                    allowed += 1  

        await message.answer(  
            "🎙 <b>LIVE STATUS</b>\n\n"  
            f"🎯 Target: {target_row['title']}\n"  
            f"📺 Live: {live_row['title']}\n\n"  
            f"👥 Target Members in Live: {members}\n"  
            f"🔇 Muted: {muted}\n"  
            f"🎤 Allowed: {allowed}\n\n"  
            "🟢 Monitor: Active",  
            parse_mode="HTML",  
            reply_markup=main_keyboard()  
        )  
    except Exception as e:  
        await message.answer(f"❌ Status Error: {e}")

async def health_handler(request):
    return web.json_response({"status": "online", "service": "Telegram Auto Speaker"})

async def start_health_server():
    app = web.Application()  
    app.router.add_get("/", health_handler)  
    app.router.add_get("/health", health_handler)  
    port = int(os.getenv("PORT", "10000"))  
    runner = web.AppRunner(app)  
    await runner.setup()  
    site = web.TCPSite(runner, "0.0.0.0", port)  
    await site.start()  
    logger.info("Health server running on port %s", port)

async def main():
    logger.info("Bot Starting...")  
    await start_health_server()  
    asyncio.create_task(auto_monitor())  
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:  
        asyncio.run(main())  
    except KeyboardInterrupt:  
        logger.info("Bot stopped")
