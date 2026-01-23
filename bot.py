import os
import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
CHAT_ID = -1002695504348 
TOPIC_ID = None # Твой ID темы

bot = Bot(token=TOKEN)
dp = Dispatcher()

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

# --- КЛАВИАТУРЫ ---
start_kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="🛡 ВСТУПИТЬ В IOT", callback_data="start_anketa")]
])

confirm_kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="✅ ОТПРАВИТЬ", callback_data="send_all"),
     InlineKeyboardButton(text="❌ ОТМЕНА", callback_data="cancel_anketa")]
])

def get_admin_kb(user_id, username):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Принять", callback_data=f"accept_{user_id}")],
        [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"decline_{user_id}")],
        [InlineKeyboardButton(text="🚫 БАН", callback_data=f"ban_{user_id}")],
        [InlineKeyboardButton(text="🗳 На голосование", callback_data=f"vote_{user_id}_{username}")]
    ])

# --- ЛОГИКА АНКЕТЫ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Привет! Ты попал в бота клана **IOT**.\nГотов заявить о себе?",
        reply_markup=start_kb
    )

@dp.callback_query(F.data == "start_anketa")
async def start_form(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("1️⃣ Отправь **Скриншот** своей статистики (одним фото):")
    await state.set_state(Form.photo)

@dp.message(Form.photo, F.photo)
async def process_photo(message: types.Message, state: FSMContext):
    await state.update_data(photo=message.photo[-1].file_id)
    await message.answer("2️⃣ Твой **Имя / Ник** в игре:")
    await state.set_state(Form.nick)

@dp.message(Form.nick)
async def process_nick(message: types.Message, state: FSMContext):
    await state.update_data(nick=message.text)
    await message.answer("3️⃣ Твой **Часовой пояс** (например, МСК+2):")
    await state.set_state(Form.timezone)

@dp.message(Form.timezone)
async def process_tz(message: types.Message, state: FSMContext):
    await state.update_data(tz=message.text)
    await message.answer("4️⃣ Есть ли у тебя **Друзья** в нашем клане?")
    await state.set_state(Form.friends)

@dp.message(Form.friends)
async def process_friends(message: types.Message, state: FSMContext):
    await state.update_data(friends=message.text)
    await message.answer("5️⃣ Предыдущий клан и **причина ухода**:")
    await state.set_state(Form.old_clan)

@dp.message(Form.old_clan)
async def process_clan(message: types.Message, state: FSMContext):
    await state.update_data(old_clan=message.text)
    await message.answer("6️⃣ Цели и планы на развитие:")
    await state.set_state(Form.goals)

@dp.message(Form.goals)
async def process_goals(message: types.Message, state: FSMContext):
    await state.update_data(goals=message.text)
    await message.answer("7️⃣ Почему именно **IOT**?")
    await state.set_state(Form.why_us)

@dp.message(Form.why_us)
async def process_why(message: types.Message, state: FSMContext):
    await state.update_data(why=message.text)
    await message.answer("8️⃣ Готов взять роль **руководителя** в будущем?")
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
    
    # Формируем превью
    summary = (
        f"📋 **ТВОЯ АНКЕТА**\n\n"
        f"• Ник: {data['nick']}\n"
        f"• Пояс: {data['tz']}\n"
        f"• Друзья: {data['friends']}\n"
        f"• Прошлый клан: {data['old_clan']}\n"
        f"• Опыт: {data['exp']}\n\n"
        "Всё верно? Если да, жми кнопку ниже."
    )
    await message.answer_photo(photo=data['photo'], caption=summary, reply_markup=confirm_kb)
    await state.set_state(Form.confirm)

@dp.callback_query(F.data == "send_all", Form.confirm)
async def finalize_anketa(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    username = callback.from_user.username or callback.from_user.first_name
    
    # Отправка админу
    await bot.send_photo(
        ADMIN_ID,
        photo=data['photo'],
        caption=f"🚀 **НОВАЯ ЗАЯВКА @{username}**\n\n"
                f"Ник: {data['nick']}\nПояс: {data['tz']}\nДрузья: {data['friends']}\n"
                f"Клан: {data['old_clan']}\nЦели: {data['goals']}\nПочему: {data['why']}\n"
                f"Лидерство: {data['leader']}\nОпыт: {data['exp']}",
        reply_markup=get_admin_kb(callback.from_user.id, username)
    )
    
    await callback.message.answer("✨ Твоя заявка успешно отправлена! Жди ответа.")
    await callback.message.delete()
    await state.clear()

@dp.callback_query(F.data == "cancel_anketa")
async def cancel_handler(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Заявка отменена. Можешь начать заново через /start")

# --- ЛОГИКА ГОЛОСОВАНИЯ (ОСТАВЛЯЕМ КАК БЫЛО ИЛИ УЛУЧШАЕМ) ---
# ... тут функции handle_vote и start_voting из прошлого сообщения ...

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
    
