import os
import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
# Твой новый ID чата:
CHAT_ID = -1002695504348 
# ID темы "Заявки" (узнай через @raw_data_bot, если не 0)
TOPIC_ID = None  # Замени на число, если это конкретная тема

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Словарь для хранения голосов: {message_id: {'yes': [user_ids], 'no': [user_ids]}}
votes_data = {}

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

def get_vote_kb(yes_count=0, no_count=0):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=f"✅ Не против [{yes_count}]", callback_data="v_yes"),
            InlineKeyboardButton(text=f"❌ Против [{no_count}]", callback_data="v_no")
        ]
    ])

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer("Добро пожаловать в IOT клан-бот!", reply_markup=main_menu)

@dp.message(F.text == "🛡 Вступить в гильдию")
async def apply_start(message: types.Message):
    text = (
        "📝 **АНКЕТА ДЛЯ ВСТУПЛЕНИЯ IOT**\n\n"
        "• Скриншот / Стат\n• Имя / Ник В игре\n• Часовой Пояс\n• Друзья в игре\n"
        "• Предыдущий Клан (Причина Покидания)\n• Цель / Планы\n"
        "• Почему выбрали нас?\n• Готовы ли быть лидером?\n• Как давно играете\n\n"
        "⚠️ Прикрепи фото и напиши анкету в описании!"
    )
    await message.answer(text)

@dp.message(F.photo)
async def handle_application(message: types.Message):
    if message.caption:
        username = message.from_user.username or message.from_user.first_name
        # Отправляем админу в ЛС для первичной проверки
        await bot.send_photo(
            ADMIN_ID,
            photo=message.photo[-1].file_id,
            caption=f"🚀 **Новая заявка от @{username}**\n\n{message.caption}",
            reply_markup=get_admin_kb(message.from_user.id, username)
        )
        await message.answer("✅ Анкета ушла на проверку!")
    else:
        await message.answer("❌ Нужно прислать ФОТО со статой и ТЕКСТ анкеты в описании.")

# --- CALLBACKS ---

@dp.callback_query(F.data.startswith("vote_"))
async def start_voting(callback: types.CallbackQuery):
    _, user_id, username = callback.data.split("_")
    
    # Отправляем в чат клана (в нужную тему)
    sent_msg = await bot.send_message(
        chat_id=CHAT_ID,
        message_thread_id=TOPIC_ID,
        text=f"🗳 **Голосование**\nИгрок @{username} хочет к нам! Что думаете?",
        reply_markup=get_vote_kb()
    )
    # Инициализируем данные голосования
    votes_data[sent_msg.message_id] = {'yes': set(), 'no': set()}
    await callback.answer("Голосование запущено!")

@dp.callback_query(F.data.startswith("v_"))
async def handle_vote(callback: types.CallbackQuery):
    msg_id = callback.message.message_id
    user_id = callback.from_user.id
    
    if msg_id not in votes_data:
        votes_data[msg_id] = {'yes': set(), 'no': set()}

    # Логика: если нажал "За", убираем из "Против" и наоборот
    if callback.data == "v_yes":
        votes_data[msg_id]['no'].discard(user_id)
        votes_data[msg_id]['yes'].add(user_id)
    else:
        votes_data[msg_id]['yes'].discard(user_id)
        votes_data[msg_id]['no'].add(user_id)

    # Обновляем кнопки с новыми цифрами
    await callback.message.edit_reply_markup(
        reply_markup=get_vote_kb(len(votes_data[msg_id]['yes']), len(votes_data[msg_id]['no']))
    )
    await callback.answer("Голос учтен!")

@dp.callback_query(F.data.startswith("accept_"))
async def accept(callback: types.CallbackQuery):
    uid = callback.data.split("_")[1]
    await bot.send_message(uid, "🎉 Поздравляем! Вас приняли. Вот ссылка: [ССЫЛКА]")
    await callback.message.edit_caption(caption=callback.message.caption + "\n\n✅ ПРИНЯТ")

@dp.callback_query(F.data.startswith("decline_"))
async def decline(callback: types.CallbackQuery):
    uid = callback.data.split("_")[1]
    await bot.send_message(uid, "❌ К сожалению, ваша заявка отклонена.")
    await callback.message.edit_caption(caption=callback.message.caption + "\n\n❌ ОТКЛОНЕН")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
