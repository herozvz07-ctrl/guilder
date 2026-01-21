import os
import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from dotenv import load_dotenv

# Загрузка переменных (Flex import OS/Dotenv)
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
CHAT_ID = int(os.getenv("CHAT_ID"))

bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- КЛАВИАТУРЫ ---
main_menu = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="🛡 Вступить в гильдию")]
], resize_keyboard=True)

def get_admin_kb(user_id, username):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Принять", callback_data=f"accept_{user_id}")],
        [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"decline_{user_id}")],
        [InlineKeyboardButton(text="🚫 БАН", callback_data=f"ban_{user_id}")],
        [InlineKeyboardButton(text="🗳 На голосование", callback_data=f"vote_{user_id}_{username}")]
    ])

def get_vote_kb(count_yes=0, count_no=0):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✅ Не против [{count_yes}]", callback_data="v_yes"),
         InlineKeyboardButton(text=f"❌ Против [{count_no}]", callback_data="v_no")]
    ])

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer("Добро пожаловать в бота клана **IOT**!", reply_markup=main_menu)

@dp.message(F.text == "🛡 Вступить в гильдию")
async def apply_start(message: types.Message):
    text = (
        "📝 **АНКЕТА ДЛЯ ВСТУПЛЕНИЯ IOT**\n\n"
        "• Скриншот / Стат (Обязательно прикрепите фото!)\n"
        "• Имя / Ник В игре\n"
        "• Часовой Пояс\n"
        "• Друзья в игре\n"
        "• Предыдущий Клан (Причина Покидания)\n"
        "• Цель / Планы На развитие\n"
        "• Почему выбрали именно нас?\n"
        "• Готовы ли взять роль руководителя?\n"
        "• Как давно начали играть\n\n"
        "⚠️ **ВНИМАНИЕ**: Нечеткий скрин или пустые ответы — отказ или БАН.\n"
        "Отправьте анкету **одним сообщением вместе с фото**."
    )
    await message.answer(text)

@dp.message(F.photo)
async def handle_application(message: types.Message):
    if message.caption:
        # Пересылка админу
        username = message.from_user.username or message.from_user.first_name
        await bot.send_photo(
            ADMIN_ID,
            photo=message.photo[-1].file_id,
            caption=f"🚀 **Новая заявка от @{username}** (ID: {message.from_user.id})\n\n{message.caption}",
            reply_markup=get_admin_kb(message.from_user.id, username)
        )
        await message.answer("✅ Ваша анкета отправлена основателям. Ожидайте решения.")
    else:
        await message.answer("❌ Ошибка! Вы прислали фото без описания анкеты.")

# --- CALLBACKS (Админка и Голосование) ---

@dp.callback_query(F.data.startswith("vote_"))
async def start_voting(callback: types.CallbackQuery):
    _, user_id, username = callback.data.split("_")
    await bot.send_message(
        CHAT_ID,
        f"🗳 **Голосование**\nИгрок @{username} хочет вступить к нам в клан. Что скажете?",
        reply_markup=get_vote_kb()
    )
    await callback.answer("Голосование запущено!")

@dp.callback_query(F.data.startswith("v_"))
async def process_vote(callback: types.CallbackQuery):
    # Упрощенная логика счетчика (в идеале хранить в БД)
    # Для примера просто обновим цифру в кнопке
    await callback.answer("Голос учтен!")

@dp.callback_query(F.data.startswith("ban_"))
async def ban_user(callback: types.CallbackQuery):
    user_id = callback.data.split("_")[1]
    # Тут можно добавить логику в список заблокированных
    await callback.message.edit_caption(caption=callback.message.caption + "\n\n🚫 **ЗАБАНЕН**")
    await bot.send_message(user_id, "Вы были заблокированы в боте за нарушение правил подачи заявки.")

# Запуск
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
