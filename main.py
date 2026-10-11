import os
import asyncio
import logging
from dotenv import load_dotenv
from aiohttp import web

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton
)
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    PasswordHashInvalidError,
    PhoneCodeExpiredError
)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "8869783838:AAFyPZC1qLvHo0cO_hWUKfgE1ERxgIUTvd8").strip()
API_HASH = os.getenv("API_HASH", "b4d288715cf8dee6c2b048d5c94881e3").strip()
API_ID = 37903178  # আপনার নির্দিষ্ট API_ID

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN missing")

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("SessionGenBot")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

temp_clients = {}
temp_data = {}

class GenStates(StatesGroup):
    waiting_phone = State()
    waiting_code = State()
    waiting_password = State()

def main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🔑 Generate String Session")]],
        resize_keyboard=True,
        is_persistent=True
    )

@router.message(CommandStart())
async def start_handler(message: Message):
    await message.answer(
        "🤖 <b>Telegram String Session Generator Bot</b>\n\n"
        "এই বটের মাধ্যমে আপনি আপনার টেলিগ্রাম অ্যাকাউন্টের String Session তৈরি করতে পারবেন।\n"
        "শুরু করতে নিচের বাটনে ক্লিক করুন:",
        parse_mode="HTML",
        reply_markup=main_keyboard()
    )

@router.message(F.text == "🔑 Generate String Session")
async def start_generation(message: Message, state: FSMContext):
    user_id = message.chat.id
    
    try:
        client = TelegramClient(StringSession(), API_ID, API_HASH, connection_retries=5)
        await client.connect()
        temp_clients[user_id] = client

        await state.set_state(GenStates.waiting_phone)
        await message.answer(
            "📱 আপনার টেলিগ্রাম অ্যাকাউন্টের ফোন নম্বরটি কান্ট্রি কোডসহ পাঠান\n"
            "(উদাহরণস্বরূপ: <code>+8801712345678</code>):",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.exception(e)
        await message.answer(f"❌ ক্লায়েন্ট কানেক্ট করা যায়নি: {e}")

@router.message(GenStates.waiting_phone)
async def process_phone(message: Message, state: FSMContext):
    phone = message.text.strip()
    user_id = message.chat.id
    client = temp_clients.get(user_id)

    if not client:
        await message.answer("❌ সেশন মেয়াদোত্তীর্ণ হয়েছে। আবার শুরু করুন।", reply_markup=main_keyboard())
        await state.clear()
        return

    try:
        sent_code = await client.send_code_request(phone)
        temp_data[user_id] = {
            "phone": phone,
            "phone_code_hash": sent_code.phone_code_hash
        }
        await state.set_state(GenStates.waiting_code)
        await message.answer(
            "📩 আপনার টেলিগ্রাম অ্যাপে একটি ওটিপি (OTP) কোড পাঠানো হয়েছে।\n"
            "কোডটি এখানে দিন (যেমন: <code>12345</code>):",
            parse_mode="HTML"
        )
    except PhoneNumberInvalidError:
        await message.answer("❌ ফোন নম্বরটি সঠিক নয়। সঠিক ফরম্যাটে আবার দিন (যেমন: <code>+8801712345678</code>):", parse_mode="HTML")
    except Exception as e:
        logger.exception(e)
        await message.answer(f"❌ কোড পাঠানো যায়নি: {e}", reply_markup=main_keyboard())
        await state.clear()

@router.message(GenStates.waiting_code)
async def process_code(message: Message, state: FSMContext):
    code = message.text.strip().replace(" ", "")
    user_id = message.chat.id
    client = temp_clients.get(user_id)
    data = temp_data.get(user_id)

    if not client or not data:
        await message.answer("❌ ডেটা পাওয়া যায়নি। আবার চেষ্টা করুন।", reply_markup=main_keyboard())
        await state.clear()
        return

    try:
        await client.sign_in(
            phone=data["phone"],
            code=code,
            phone_code_hash=data["phone_code_hash"]
        )
        
        string_session = client.session.save()
        await client.disconnect()
        
        await state.clear()
        temp_clients.pop(user_id, None)
        temp_data.pop(user_id, None)

        await message.answer(
            "✅ <b>সফলভাবে String Session তৈরি হয়েছে!</b>\n\n"
            "নিচের স্ট্রিং কোডটি কপি করে নিরাপদ স্থানে রাখুন:\n\n"
            f"<code>{string_session}</code>",
            parse_mode="HTML",
            reply_markup=main_keyboard()
        )

    except SessionPasswordNeededError:
        await state.set_state(GenStates.waiting_password)
        await message.answer(
            "🔐 আপনার অ্যাকাউন্টে 2-Step Verification (2FA) চালু আছে।\n"
            "দয়া করে আপনার ক্লাউড পাসওয়ার্ডটি এখানে দিন:",
            parse_mode="HTML"
        )
    except (PhoneCodeInvalidError, PhoneCodeExpiredError):
        await message.answer("❌ ওটিপি কোডটি ভুল বা মেয়াদোত্তীর্ণ। সঠিক কোডটি আবার দিন:")
    except Exception as e:
        logger.exception(e)
        await message.answer(f"❌ লগইন ব্যর্থ হয়েছে: {e}", reply_markup=main_keyboard())
        await state.clear()

@router.message(GenStates.waiting_password)
async def process_password(message: Message, state: FSMContext):
    password = message.text.strip()
    user_id = message.chat.id
    client = temp_clients.get(user_id)

    if not client:
        await message.answer("❌ সেশন বাতিল হয়েছে। আবার চেষ্টা করুন।", reply_markup=main_keyboard())
        await state.clear()
        return

    try:
        await client.sign_in(password=password)
        
        string_session = client.session.save()
        await client.disconnect()

        await state.clear()
        temp_clients.pop(user_id, None)
        temp_data.pop(user_id, None)

        await message.answer(
            "✅ <b>2FA দিয়ে সফলভাবে String Session তৈরি হয়েছে!</b>\n\n"
            "নিচের কোডটি কপি করে নিরাপদ স্থানে রাখুন:\n\n"
            f"<code>{string_session}</code>",
            parse_mode="HTML",
            reply_markup=main_keyboard()
        )

    except PasswordHashInvalidError:
        await message.answer("❌ পাসওয়ার্ড ভুল হয়েছে। সঠিক পাসওয়ার্ডটি আবার দিন:")
    except Exception as e:
        logger.exception(e)
        await message.answer(f"❌ প্রসেস সম্পন্ন করা যায়নি: {e}", reply_markup=main_keyboard())
        await state.clear()

async def health_handler(request):
    return web.json_response({"status": "online", "service": "Session Generator Bot"})

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
    logger.info("Session Generator Bot Starting...")
    await start_health_server()
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped.")
