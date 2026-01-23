import os
import asyncio
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

# Загрузка настроек
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
CHAT_ID = -1002695504348  # Твой ID чата
TOPIC_ID = None           # ID темы (если есть)

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Хранилище голосов (в памяти)
votes_data = {}

# Состояния анкеты
class Form(StatesGroup):
    photo = State()
    nick = State()
    timezone = State()
    friends = State()
    old_clan = State()
    goals = State()
    why_us = State()
    leader_role = State()
    experience = State()
    confirm = State()

# --- ВЕБ-СЕРВЕР ДЛЯ RENDER (ФИКС ПОРТА) ---
async def handle(request):
    return web.Response(text="IOT Clan Bot is Alive!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

# --- КЛАВИАТУРЫ ---
def get_start_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛡 Вступить в IOT", callback_data="start_anketa")]
    ])

def get_confirm_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Отправить", callback_data="send_all"),
         InlineKeyboardButton(text="❌ Сброс", callback_data="cancel_anketa")]
    ])

def get_admin_kb(user_id, username):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Принять", callback_data=f"accept_{user_id}"),
         InlineKeyboardButton(text="❌ Отказать", callback_data=f"decline_{user_id}")],
        [InlineKeyboardButton(text="🗳 На голосование", callback_data=f"vote_{user_id}_{username}")],
        [InlineKeyboardButton(text="🚫 БАН", callback_data=f"ban_{user_id}")]
    ])

def get_vote_kb(yes=0, no=0):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✅ За [{yes}]", callback_data="v_yes"),
         InlineKeyboardButton(text=f"❌ Против [{no}]", callback_data="v_no")]
    ])

# --- ОБРАБОТКА КОМАНД ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Привет! Это бот клана **IOT**.\nНажми кнопку ниже, чтобы подать заявку.",
        reply_markup=get_start_kb()
    )

@dp.callback_query(F.data == "start_anketa")
async def start_form(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("1️⃣ Пришли **скриншот** твоей статистики (одним фото):")
    await state.set_state(Form.photo)
    await callback.answer()

@dp.message(Form.photo, F.photo)
async def process_photo(message: types.Message, state: FSMContext):
    await state.update_data(photo=message.photo[-1].file_id)
    await message.answer("2️⃣ Твой **Ник** в игре:")
    await state.set_state(Form.nick)

@dp.message(Form.nick)
async def process_nick(message: types.Message, state: FSMContext):
    await state.update_data(nick=message.text)
    await message.answer("3️⃣ Твой **Часовой пояс** (например, МСК или +3):")
    await state.set_state(Form.timezone)

@dp.message(Form.timezone)
async def process_tz(message: types.Message, state: FSMContext):
    await state.update_data(tz=message.text)
    await message.answer("4️⃣ **Друзья** в клане (если есть):")
    await state.set_state(Form.friends)

@dp.message(Form.friends)
async def process_friends(message: types.Message, state: FSMContext):
    await state.update_data(friends=message.text)
    await message.answer("5️⃣ Предыдущий клан и причина ухода:")
    await state.set_state(Form.old_clan)

@dp.message(Form.old_clan)
async def process_clan(message: types.Message, state: FSMContext):
    await state.update_data(old_clan=message.text)
    await message.answer("6️⃣ Цели и планы на будущее:")
    await state.set_state(Form.goals)

@dp.message(Form.goals)
async def process_goals(message: types.Message, state: FSMContext):
    await state.update_data(goals=message.text)
    await message.answer("7️⃣ Почему именно мы?")
    await state.set_state(Form.why_us)

@dp.message(Form.why_us)
async def process_why(message: types.Message, state: FSMContext):
    await state.update_data(why=message.text)
    await message.answer("8️⃣ Готов взять на себя роль руководителя?")
    await state.set_state(Form.leader_role)

@dp.message(Form.leader_role)
async def process_leader(message: types.Message, state: FSMContext):
    await state.update_data(leader=message.text)
    await message.answer("9️⃣ Как давно начал играть?")
    await state.set_state(Form.experience)

@dp.message(Form.experience)
async def process_exp(message: types.Message, state: FSMContext):
    await state.update_data(exp=message.text)
    data = await state.get_data()
    
    summary = (
        f"🔎 **ПРОВЕРЬ АНКЕТУ**\n\n"
        f"👤 Ник: {data['nick']}\n"
        f"🌍 Пояс: {data['tz']}\n"
        f"🎮 Опыт: {data['exp']}\n\n"
        "Отправляем?"
    )
    await message.answer_photo(photo=data['photo'], caption=summary, reply_markup=get_confirm_kb())
    await state.set_state(Form.confirm)

@dp.callback_query(F.data == "send_all", Form.confirm)
async def finalize_anketa(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    username = callback.from_user.username or "без ника"
    
    await bot.send_photo(
        ADMIN_ID,
        photo=data['photo'],
        caption=f"🚀 **НОВАЯ ЗАЯВКА @{username}**\n\n"
                f"Ник: {data['nick']}\nПояс: {data['tz']}\nДрузья: {data['friends']}\n"
                f"Клан: {data['old_clan']}\nПланы: {data['goals']}\nПочему: {data['why']}\n"
                f"Лидер: {data['leader']}\nОпыт: {data['exp']}",
        reply_markup=get_admin_kb(callback.from_user.id, username)
    )
    await callback.message.answer("✅ Заявка отправлена основателям!")
    await callback.message.delete()
    await state.clear()

@dp.callback_query(F.data == "cancel_anketa")
async def cancel_anketa(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Заявка отменена.")

# --- АДМИН-ДЕЙСТВИЯ И ГОЛОСОВАНИЕ ---

@dp.callback_query(F.data.startswith("vote_"))
async def start_voting(callback: types.CallbackQuery):
    _, user_id, username = callback.data.split("_")
    msg = await bot.send_message(
        CHAT_ID, 
        f"🗳 **Голосование**\nИгрок @{username} (ID: {user_id}) хочет в клан. Вы за?",
        reply_markup=get_vote_kb(),
        message_thread_id=TOPIC_ID
    )
    votes_data[msg.message_id] = {"yes": set(), "no": set()}
    await callback.answer("Голосование запущено!")

@dp.callback_query(F.data.startswith("v_"))
async def handle_vote(callback: types.CallbackQuery):
    msg_id = callback.message.message_id
    uid = callback.from_user.id
    if msg_id not in votes_data: votes_data[msg_id] = {"yes": set(), "no": set()}
    
    if callback.data == "v_yes":
        votes_data[msg_id]["no"].discard(uid)
        votes_data[msg_id]["yes"].add(uid)
    else:
        votes_data[msg_id]["yes"].discard(uid)
        votes_data[msg_id]["no"].add(uid)
    
    await callback.message.edit_reply_markup(
        reply_markup=get_vote_kb(len(votes_data[msg_id]["yes"]), len(votes_data[msg_id]["no"]))
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("accept_"))
async def accept_user(callback: types.CallbackQuery):
    user_id = callback.data.split("_")[1]
    await bot.send_message(user_id, "🎉 Вас приняли в IOT! Добро пожаловать.")
    await callback.message.edit_caption(caption=callback.message.caption + "\n\n✅ ПРИНЯТ")

@dp.callback_query(F.data.startswith("decline_"))
async def decline_user(callback: types.CallbackQuery):
    user_id = callback.data.split("_")[1]
    await bot.send_message(user_id, "❌ Ваша заявка отклонена.")
    await callback.message.edit_caption(caption=callback.message.caption + "\n\n❌ ОТКЛОНЕН")

@dp.callback_query(F.data.startswith("ban_"))
async def ban_user(callback: types.CallbackQuery):
    user_id = callback.data.split("_")[1]
    await bot.send_message(user_id, "🚫 Вы забанены в боте.")
    await callback.message.edit_caption(caption=callback.message.caption + "\n\n🚫 ЗАБАНЕН")

# --- ЗАПУСК ---
async def main():
    asyncio.create_task(start_web_server()) # Запуск веба для Render
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
    
