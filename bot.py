import os
import asyncio
import json
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Файл для хранения настроек чата
CONFIG_FILE = "chat_config.json"

def save_config(chat_id, topic_id):
    with open(CONFIG_FILE, "w") as f:
        json.dump({"chat_id": chat_id, "topic_id": topic_id}, f)

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {"chat_id": None, "topic_id": None}

# Хранилище голосов
votes_data = {}

class Form(StatesGroup):
    photo, nick, timezone, friends, old_clan, goals, why_us, leader_role, experience, confirm = [State() for _ in range(10)]

# --- ВЕБ-СЕРВЕР ДЛЯ RENDER ---
async def handle(request): return web.Response(text="Bot is Alive!")
async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(os.environ.get("PORT", 8080)))
    await site.start()

# --- КОМАНДА НАСТРОЙКИ (ТОЛЬКО ДЛЯ АДМИНА) ---
@dp.message(Command("setup"))
async def cmd_setup(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return

    chat_id = message.chat.id
    topic_id = message.message_thread_id if message.is_topic_message else None
    
    save_config(chat_id, topic_id)
    
    topic_text = f"тема ID: {topic_id}" if topic_id else "основной чат"
    await message.answer(f"✅ **Настройка выполнена!**\nТеперь заявки на голосование будут приходить сюда ({topic_text}).")

# --- КЛАВИАТУРЫ ---
def get_start_kb():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🛡 Вступить в IOT", callback_data="start_anketa")]])

def get_confirm_kb():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Отправить", callback_data="send_all"), InlineKeyboardButton(text="❌ Сброс", callback_data="cancel_anketa")]])

def get_admin_kb(user_id, username):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Принять", callback_data=f"accept_{user_id}"), InlineKeyboardButton(text="❌ Отказать", callback_data=f"decline_{user_id}")],
        [InlineKeyboardButton(text="🗳 На голосование", callback_data=f"vote_{user_id}_{username}")],
        [InlineKeyboardButton(text="🚫 БАН", callback_data=f"ban_{user_id}")]
    ])

def get_vote_kb(yes=0, no=0):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"✅ За [{yes}]", callback_data="v_yes"), InlineKeyboardButton(text=f"❌ Против [{no}]", callback_data="v_no")]])

# --- ЛОГИКА АНКЕТЫ ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("👋 Привет! Это бот клана **IOT**.", reply_markup=get_start_kb())

@dp.callback_query(F.data == "start_anketa")
async def start_form(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("1️⃣ Пришли **скриншот** статистики:")
    await state.set_state(Form.photo)

@dp.message(Form.photo, F.photo)
async def process_photo(message: types.Message, state: FSMContext):
    await state.update_data(photo=message.photo[-1].file_id)
    await message.answer("2️⃣ Твой **Ник**:")
    await state.set_state(Form.nick)

@dp.message(Form.nick)
async def process_nick(message: types.Message, state: FSMContext):
    await state.update_data(nick=message.text)
    await message.answer("3️⃣ Твой **Часовой пояс**:")
    await state.set_state(Form.timezone)

@dp.message(Form.timezone)
async def process_tz(message: types.Message, state: FSMContext):
    await state.update_data(tz=message.text)
    await message.answer("4️⃣ **Друзья** в клане:")
    await state.set_state(Form.friends)

@dp.message(Form.friends)
async def process_friends(message: types.Message, state: FSMContext):
    await state.update_data(friends=message.text)
    await message.answer("5️⃣ Прошлый клан и причина ухода:")
    await state.set_state(Form.old_clan)

@dp.message(Form.old_clan)
async def process_clan(message: types.Message, state: FSMContext):
    await state.update_data(old_clan=message.text)
    await message.answer("6️⃣ Планы на будущее:")
    await state.set_state(Form.goals)

@dp.message(Form.goals)
async def process_goals(message: types.Message, state: FSMContext):
    await state.update_data(goals=message.text)
    await message.answer("7️⃣ Почему мы?")
    await state.set_state(Form.why_us)

@dp.message(Form.why_us)
async def process_why(message: types.Message, state: FSMContext):
    await state.update_data(why=message.text)
    await message.answer("8️⃣ Готов быть лидером?")
    await state.set_state(Form.leader_role)

@dp.message(Form.leader_role)
async def process_leader(message: types.Message, state: FSMContext):
    await state.update_data(leader=message.text)
    await message.answer("9️⃣ Как давно играешь?")
    await state.set_state(Form.experience)

@dp.message(Form.experience)
async def process_exp(message: types.Message, state: FSMContext):
    await state.update_data(exp=message.text)
    data = await state.get_data()
    summary = f"🔎 **ПРОВЕРЬ АНКЕТУ**\n\n👤 Ник: {data['nick']}\n🌍 Пояс: {data['tz']}\n🎮 Опыт: {data['exp']}"
    await message.answer_photo(photo=data['photo'], caption=summary, reply_markup=get_confirm_kb())
    await state.set_state(Form.confirm)

@dp.callback_query(F.data == "send_all", Form.confirm)
async def finalize_anketa(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    username = callback.from_user.username or "id" + str(callback.from_user.id)
    await bot.send_photo(ADMIN_ID, photo=data['photo'], 
        caption=f"🚀 **ЗАЯВКА @{username}**\nНик: {data['nick']}\nПояс: {data['tz']}\nКлан: {data['old_clan']}\nОпыт: {data['exp']}",
        reply_markup=get_admin_kb(callback.from_user.id, username))
    await callback.message.answer("✅ Отправлено!")
    await state.clear()

# --- ГОЛОСОВАНИЕ И ПРИЕМ ---
@dp.callback_query(F.data.startswith("vote_"))
async def start_voting(callback: types.CallbackQuery):
    config = load_config()
    if not config["chat_id"]:
        await callback.answer("⚠️ Чат не настроен! Напиши /setup в группе.", show_alert=True)
        return

    _, user_id, username = callback.data.split("_")
    msg = await bot.send_message(config["chat_id"], f"🗳 **Голосование**\nИгрок @{username} хочет к нам!",
        reply_markup=get_vote_kb(), message_thread_id=config["topic_id"])
    votes_data[msg.message_id] = {"yes": set(), "no": set()}
    await callback.answer("Голосование запущено!")

@dp.callback_query(F.data.startswith("v_"))
async def handle_vote(callback: types.CallbackQuery):
    mid, uid = callback.message.message_id, callback.from_user.id
    if mid not in votes_data: votes_data[mid] = {"yes": set(), "no": set()}
    if callback.data == "v_yes":
        votes_data[mid]["no"].discard(uid); votes_data[mid]["yes"].add(uid)
    else:
        votes_data[mid]["yes"].discard(uid); votes_data[mid]["no"].add(uid)
    await callback.message.edit_reply_markup(reply_markup=get_vote_kb(len(votes_data[mid]["yes"]), len(votes_data[mid]["no"])))

@dp.callback_query(F.data.startswith("accept_"))
async def accept_user(callback: types.CallbackQuery):
    await bot.send_message(callback.data.split("_")[1], "🎉 Вас приняли!")
    await callback.message.edit_caption(caption=callback.message.caption + "\n\n✅ ПРИНЯТ")

@dp.callback_query(F.data.startswith("decline_"))
async def decline_user(callback: types.CallbackQuery):
    await bot.send_message(callback.data.split("_")[1], "❌ Отказано.")
    await callback.message.edit_caption(caption=callback.message.caption + "\n\n❌ ОТКЛОНЕН")

async def main():
    asyncio.create_task(start_web_server())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
    
