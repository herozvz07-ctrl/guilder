import os
import asyncio
import logging
import aiohttp
from datetime import datetime, timedelta
from typing import Optional, Dict, List

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from aiohttp import web
from motor.motor_asyncio import AsyncIOMotorClient
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== КОНФИГУРАЦИЯ ====================
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
PORT = int(os.getenv("PORT", 8080))

# Твой личный ID как владельца (для /setguild)
OWNER_ID = int(os.getenv("ADMIN_ID", "0")) 
# ID админ-чата (куда летят анкеты)
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))

# Инициализация
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()

# БД
mongo_client = AsyncIOMotorClient(MONGO_URI)
db = mongo_client.rucoy_guild
guild_col = db.guild
users_col = db.users
applications_col = db.applications
logs_col = db.logs

class ApplicationForm(StatesGroup):
    screenshot = State()
    game_nick = State()
    timezone = State()
    friends = State()
    prev_guild = State()
    goals = State()
    why_guild = State()
    ready_lead = State()
    play_time = State()
    confirm = State()

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================

async def get_user_role(user_id: int) -> str:
    """Получить роль пользователя"""
    user = await users_col.find_one({"tg_id": user_id})
    return user.get("role", "member") if user else "member"

async def is_admin(user_id: int) -> bool:
    """Проверка админских прав"""
    role = await get_user_role(user_id)
    return role in ["owner", "admin"]

async def log_action(action: str, by_admin: int, target_user: Optional[int] = None, details: Optional[Dict] = None):
    """Логирование действий"""
    await logs_col.insert_one({
        "action": action,
        "by_admin": by_admin,
        "target_user": target_user,
        "details": details or {},
        "date": datetime.now()
    })

def get_main_keyboard() -> InlineKeyboardMarkup:
    """Главное меню"""
    buttons = [
        [InlineKeyboardButton(text="🔰 Вступить в гильдию", callback_data="apply")],
        [InlineKeyboardButton(text="🏰 Информация о гильдии", callback_data="guild_info")],
        [InlineKeyboardButton(text="👥 Список участников", callback_data="guild_members")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="stats")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_admin_keyboard() -> InlineKeyboardMarkup:
    """Админ-панель"""
    buttons = [
        [InlineKeyboardButton(text="📋 Заявки", callback_data="admin_applications")],
        [InlineKeyboardButton(text="👑 Лидеры", callback_data="admin_leaders")],
        [InlineKeyboardButton(text="⚙️ Настройки гильдии", callback_data="admin_settings")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ==================== ПАРСИНГ ГИЛЬДИИ ====================

async def parse_guild_page(url: str) -> Optional[Dict]:
    """Парсинг страницы гильдии Rucoy"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status != 200:
                    return None
                html = await response.text()
                
        soup = BeautifulSoup(html, 'html.parser')
        
        # Парсинг данных (адаптировать под реальную структуру страницы)
        members = []
        # Пример парсинга - нужно адаптировать под реальную структуру
        member_rows = soup.select('.guild-member')  # Пример селектора
        
        for row in member_rows:
            nick = row.select_one('.nick').text.strip() if row.select_one('.nick') else "Unknown"
            level_text = row.select_one('.level').text.strip() if row.select_one('.level') else "0"
            level = int(level_text) if level_text.isdigit() else 0
            
            members.append({
                "nick": nick,
                "level": level,
                "last_seen": datetime.now(),
                "is_leader": False
            })
        
        guild_name = soup.select_one('.guild-name').text.strip() if soup.select_one('.guild-name') else "Unknown Guild"
        
        return {
            "name": guild_name,
            "url": url,
            "members": members,
            "last_update": datetime.now()
        }
    except Exception as e:
        logger.error(f"Ошибка парсинга гильдии: {e}")
        return None

async def update_guild_data():
    """Обновление данных гильдии"""
    guild_data = await guild_col.find_one()
    if not guild_data or "url" not in guild_data:
        return
    
    new_data = await parse_guild_page(guild_data["url"])
    if not new_data:
        return
    
    old_members = {m["nick"]: m for m in guild_data.get("members", [])}
    new_members = {m["nick"]: m for m in new_data["members"]}
    
    # Проверка новых участников
    for nick in new_members:
        if nick not in old_members:
            await bot.send_message(
                GUILD_CHAT_ID,
                f"🟢 <b>{nick}</b> вступил в гильдию!"
            )
    
    # Проверка ушедших участников
    for nick in old_members:
        if nick not in new_members:
            await bot.send_message(
                GUILD_CHAT_ID,
                f"🔴 <b>{nick}</b> покинул клан"
            )
            await bot.send_message(
                ADMIN_CHAT_ID,
                f"⚠️ Игрок <b>{nick}</b> покинул гильдию"
            )
    
    # Сохранение лидеров из старых данных
    for member in new_data["members"]:
        if member["nick"] in old_members:
            member["is_leader"] = old_members[member["nick"]].get("is_leader", False)
            member["last_seen"] = old_members[member["nick"]].get("last_seen", datetime.now())
    
    await guild_col.update_one(
        {},
        {"$set": new_data},
        upsert=True
    )

async def check_inactive_members():
    """Проверка неактивных участников"""
    guild_data = await guild_col.find_one()
    if not guild_data:
        return
    
    inactive_threshold = datetime.now() - timedelta(days=7)
    
    for member in guild_data.get("members", []):
        last_seen = member.get("last_seen", datetime.now())
        if last_seen < inactive_threshold:
            await bot.send_message(
                ADMIN_CHAT_ID,
                f"🟡 Игрок <b>{member['nick']}</b> не активен более 7 дней\n"
                f"Последняя активность: {last_seen.strftime('%d.%m.%Y')}"
            )

# ==================== ОБРАБОТЧИКИ КОМАНД ====================

@router.message(Command("start"))
async def cmd_start(message: Message):
    """Стартовая команда"""
    user_id = message.from_user.id
    
    # Проверка бана
    user = await users_col.find_one({"tg_id": user_id})
    if user and user.get("role") == "banned":
        await message.answer("⛔ Вы заблокированы и не можете использовать бота.")
        return
    
    # Регистрация нового пользователя
    if not user:
        await users_col.insert_one({
            "tg_id": user_id,
            "username": message.from_user.username or "unknown",
            "role": "member",
            "joined_at": datetime.now()
        })
    
    role = await get_user_role(user_id)
    
    welcome_text = (
        f"👋 Привет, <b>{message.from_user.first_name}</b>!\n\n"
        "Это бот для управления гильдией <b>Imperia Of Titans</b> в Rucoy Online.\n\n"
        "Выберите действие:"
    )
    
    keyboard = get_main_keyboard()
    
    if role in ["owner", "admin"]:
        keyboard.inline_keyboard.append(
            [InlineKeyboardButton(text="⚙️ Админ-панель", callback_data="admin_panel")]
        )
    
    await message.answer(welcome_text, reply_markup=keyboard)

@router.callback_query(F.data == "main_menu")
async def show_main_menu(callback: CallbackQuery):
    """Показать главное меню"""
    await callback.message.edit_text(
        "Выберите действие:",
        reply_markup=get_main_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data == "admin_panel")
async def show_admin_panel(callback: CallbackQuery):
    """Админ-панель"""
    if not await is_admin(callback.from_user.id):
        await callback.answer("❌ У вас нет прав доступа", show_alert=True)
        return
    
    await callback.message.edit_text(
        "⚙️ <b>Админ-панель</b>\n\nВыберите действие:",
        reply_markup=get_admin_keyboard()
    )
    await callback.answer()

# ==================== ЗАЯВКИ В ГИЛЬДИЮ ====================

@router.callback_query(F.data == "apply")
async def start_application(callback: CallbackQuery, state: FSMContext):
    """Начало заявки"""
    user_id = callback.from_user.id
    
    # Проверка существующей заявки
    existing = await applications_col.find_one({
        "user_id": user_id,
        "status": "pending"
    })
    
    if existing:
        await callback.answer("❌ У вас уже есть активная заявка", show_alert=True)
        return
    
    await state.set_state(ApplicationForm.screenshot)
    await callback.message.edit_text(
        "📝 <b>Заявка в гильдию</b>\n\n"
        "Шаг 1/9: Отправьте скриншот вашей статистики в игре"
    )
    await callback.answer()

@router.message(ApplicationForm.screenshot, F.photo)
async def process_screenshot(message: Message, state: FSMContext):
    """Обработка скриншота"""
    photo_id = message.photo[-1].file_id
    await state.update_data(screenshot=photo_id)
    await state.set_state(ApplicationForm.game_nick)
    
    await message.answer(
        "Шаг 2/9: Введите ваш игровой ник"
    )

@router.message(ApplicationForm.screenshot)
async def invalid_screenshot(message: Message):
    """Неверный формат скриншота"""
    await message.answer("❌ Пожалуйста, отправьте фото (скриншот статистики)")

@router.message(ApplicationForm.game_nick)
async def process_game_nick(message: Message, state: FSMContext):
    """Обработка игрового ника"""
    if len(message.text.strip()) < 2:
        await message.answer("❌ Ник слишком короткий. Попробуйте снова:")
        return
    
    await state.update_data(game_nick=message.text.strip())
    await state.set_state(ApplicationForm.timezone)
    await message.answer("Шаг 3/9: Укажите ваш часовой пояс (например: UTC+3)")

@router.message(ApplicationForm.timezone)
async def process_timezone(message: Message, state: FSMContext):
    """Обработка часового пояса"""
    await state.update_data(timezone=message.text.strip())
    await state.set_state(ApplicationForm.friends)
    await message.answer("Шаг 4/9: Есть ли у вас друзья в игре? Если да, напишите их ники")

@router.message(ApplicationForm.friends)
async def process_friends(message: Message, state: FSMContext):
    """Обработка друзей"""
    await state.update_data(friends=message.text.strip())
    await state.set_state(ApplicationForm.prev_guild)
    await message.answer("Шаг 5/9: В каком клане вы были ранее и почему ушли?")

@router.message(ApplicationForm.prev_guild)
async def process_prev_guild(message: Message, state: FSMContext):
    """Обработка предыдущего клана"""
    if len(message.text.strip()) < 10:
        await message.answer("❌ Ответ слишком короткий. Пожалуйста, опишите подробнее:")
        return
    
    await state.update_data(prev_guild=message.text.strip())
    await state.set_state(ApplicationForm.goals)
    await message.answer("Шаг 6/9: Какие у вас цели развития в игре?")

@router.message(ApplicationForm.goals)
async def process_goals(message: Message, state: FSMContext):
    """Обработка целей"""
    if len(message.text.strip()) < 10:
        await message.answer("❌ Ответ слишком короткий. Пожалуйста, опишите подробнее:")
        return
    
    await state.update_data(goals=message.text.strip())
    await state.set_state(ApplicationForm.why_guild)
    await message.answer("Шаг 7/9: Почему вы выбрали именно нашу гильдию?")

@router.message(ApplicationForm.why_guild)
async def process_why_guild(message: Message, state: FSMContext):
    """Обработка причины выбора гильдии"""
    if len(message.text.strip()) < 10:
        await message.answer("❌ Ответ слишком короткий. Пожалуйста, опишите подробнее:")
        return
    
    await state.update_data(why_guild=message.text.strip())
    await state.set_state(ApplicationForm.ready_lead)
    await message.answer("Шаг 8/9: Готовы ли вы быть руководителем в будущем?")

@router.message(ApplicationForm.ready_lead)
async def process_ready_lead(message: Message, state: FSMContext):
    """Обработка готовности к лидерству"""
    await state.update_data(ready_lead=message.text.strip())
    await state.set_state(ApplicationForm.play_time)
    await message.answer("Шаг 9/9: Как давно вы играете в Rucoy Online?")

@router.message(ApplicationForm.play_time)
async def process_play_time(message: Message, state: FSMContext):
    """Обработка времени игры"""
    await state.update_data(play_time=message.text.strip())
    
    data = await state.get_data()
    
    # Формирование подтверждения
    confirm_text = (
        "✅ <b>Проверьте вашу заявку:</b>\n\n"
        f"👤 Игровой ник: <b>{data['game_nick']}</b>\n"
        f"🕐 Часовой пояс: {data['timezone']}\n"
        f"👥 Друзья в игре: {data['friends']}\n"
        f"🏰 Предыдущий клан: {data['prev_guild']}\n"
        f"🎯 Цели: {data['goals']}\n"
        f"💭 Почему наша гильдия: {data['why_guild']}\n"
        f"👑 Готовность к лидерству: {data['ready_lead']}\n"
        f"⏱ Играет: {data['play_time']}\n\n"
        "Всё верно?"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Отправить", callback_data="confirm_application"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_application")
        ]
    ])
    
    await state.set_state(ApplicationForm.confirm)
    await message.answer(confirm_text, reply_markup=keyboard)

@router.callback_query(F.data == "confirm_application", StateFilter(ApplicationForm.confirm))
async def confirm_application(callback: CallbackQuery, state: FSMContext):
    """Подтверждение заявки"""
    data = await state.get_data()
    user_id = callback.from_user.id
    username = callback.from_user.username or "без username"
    
    # Сохранение в БД
    app_id = await applications_col.insert_one({
        "user_id": user_id,
        "username": username,
        "answers": data,
        "status": "pending",
        "votes_yes": [],
        "votes_no": [],
        "created_at": datetime.now()
    })
    
    # Отправка админам
    admin_text = (
        "📋 <b>НОВАЯ ЗАЯВКА В ГИЛЬДИЮ</b>\n\n"
        f"👤 Telegram: @{username}\n"
        f"🎮 Игровой ник: <b>{data['game_nick']}</b>\n\n"
        f"🕐 Часовой пояс: {data['timezone']}\n"
        f"👥 Друзья: {data['friends']}\n"
        f"🏰 Предыдущий клан: {data['prev_guild']}\n"
        f"🎯 Цели: {data['goals']}\n"
        f"💭 Почему мы: {data['why_guild']}\n"
        f"👑 Готов к лидерству: {data['ready_lead']}\n"
        f"⏱ Играет: {data['play_time']}\n"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Принять", callback_data=f"accept_{app_id.inserted_id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{app_id.inserted_id}")
        ],
        [
            InlineKeyboardButton(text="⛔ Бан", callback_data=f"ban_{app_id.inserted_id}"),
            InlineKeyboardButton(text="🗳 Голосование", callback_data=f"vote_{app_id.inserted_id}")
        ]
    ])
    
    # Отправка скриншота
    await bot.send_photo(
        ADMIN_CHAT_ID,
        photo=data['screenshot'],
        caption=admin_text,
        reply_markup=keyboard
    )
    
    await state.clear()
    await callback.message.edit_text(
        "✅ Ваша заявка отправлена на рассмотрение!\n"
        "Мы свяжемся с вами в ближайшее время."
    )
    await callback.answer()

@router.callback_query(F.data == "cancel_application")
async def cancel_application(callback: CallbackQuery, state: FSMContext):
    """Отмена заявки"""
    await state.clear()
    await callback.message.edit_text("❌ Заявка отменена")
    await callback.answer()

# ==================== ОБРАБОТКА ЗАЯВОК АДМИНАМИ ====================

@router.callback_query(F.data.startswith("accept_"))
async def accept_application(callback: CallbackQuery):
    """Принятие заявки"""
    if not await is_admin(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return
    
    app_id = callback.data.split("_")[1]
    
    app = await applications_col.find_one({"_id": app_id})
    if not app:
        await callback.answer("❌ Заявка не найдена", show_alert=True)
        return
    
    await applications_col.update_one(
        {"_id": app_id},
        {"$set": {"status": "accepted"}}
    )
    
    await users_col.update_one(
        {"tg_id": app["user_id"]},
        {"$set": {"game_nick": app["answers"]["game_nick"], "role": "member"}},
        upsert=True
    )
    
    await log_action("application_accepted", callback.from_user.id, app["user_id"])
    
    await bot.send_message(
        app["user_id"],
        f"🎉 Поздравляем! Ваша заявка одобрена!\n"
        f"Добро пожаловать в гильдию <b>Imperia Of Titans</b>!"
    )
    
    await callback.message.edit_caption(
        caption=callback.message.caption + f"\n\n✅ Принята ({callback.from_user.username})"
    )
    await callback.answer("✅ Заявка принята")

@router.callback_query(F.data.startswith("reject_"))
async def reject_application(callback: CallbackQuery):
    """Отклонение заявки"""
    if not await is_admin(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return
    
    app_id = callback.data.split("_")[1]
    
    app = await applications_col.find_one({"_id": app_id})
    if not app:
        await callback.answer("❌ Заявка не найдена", show_alert=True)
        return
    
    await applications_col.update_one(
        {"_id": app_id},
        {"$set": {"status": "rejected"}}
    )
    
    await log_action("application_rejected", callback.from_user.id, app["user_id"])
    
    await bot.send_message(
        app["user_id"],
        "😔 К сожалению, ваша заявка отклонена.\n"
        "Вы можете попробовать подать заявку снова позже."
    )
    
    await callback.message.edit_caption(
        caption=callback.message.caption + f"\n\n❌ Отклонена ({callback.from_user.username})"
    )
    await callback.answer("❌ Заявка отклонена")

@router.callback_query(F.data.startswith("ban_"))
async def ban_application(callback: CallbackQuery):
    """Бан пользователя"""
    if not await is_admin(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return
    
    app_id = callback.data.split("_")[1]
    
    app = await applications_col.find_one({"_id": app_id})
    if not app:
        await callback.answer("❌ Заявка не найдена", show_alert=True)
        return
    
    await applications_col.update_one(
        {"_id": app_id},
        {"$set": {"status": "accepted"}}
    )
    
    await users_col.update_one(
        {"tg_id": app["user_id"]},
        {"$set": {"game_nick": app["answers"]["game_nick"], "role": "member"}},
        upsert=True
    )
    
    await log_action("application_accepted", callback.from_user.id, app["user_id"])
    
    await bot.send_message(
        app["user_id"],
        f"🎉 Поздравляем! Ваша заявка одобрена!\n"
        f"Добро пожаловать в гильдию <b>Imperia Of Titans</b>!"
    )
    
    await callback.message.edit_caption(
        caption=callback.message.caption + f"\n\n✅ Принята ({callback.from_user.username})"
    )
    await callback.answer("✅ Заявка принята")

@router.callback_query(F.data.startswith("reject_"))
async def reject_application(callback: CallbackQuery):
    """Отклонение заявки"""
    if not await is_admin(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return
    
    app_id = callback.data.split("_")[1]
    
    app = await applications_col.find_one({"_id": app_id})
    if not app:
        await callback.answer("❌ Заявка не найдена", show_alert=True)
        return
    
    await applications_col.update_one(
        {"_id": app_id},
        {"$set": {"status": "rejected"}}
    )
    
    await log_action("application_rejected", callback.from_user.id, app["user_id"])
    
    await bot.send_message(
        app["user_id"],
        "😔 К сожалению, ваша заявка отклонена.\n"
        "Вы можете попробовать подать заявку снова позже."
    )
    
    await callback.message.edit_caption(
        caption=callback.message.caption + f"\n\n❌ Отклонена ({callback.from_user.username})"
    )
    await callback.answer("❌ Заявка отклонена")

@router.callback_query(F.data.startswith("ban_"))
async def ban_application(callback: CallbackQuery):
    """Бан пользователя"""
    if not await is_admin(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return
    
    app_id = callback.data.split("_")[1]
    
    app = await applications_col.find_one({"_id": app_id})
    if not app:
        await callback.answer("❌ Заявка не найдена", show_alert=True)
        return
    
    await applications_col.update_one(
        {"_id": app_id},
        {"$set": {"status": "banned"}}
    )
    
    await users_col.update_one(
        {"tg_id": app["user_id"]},
        {"$set": {"role": "banned"}},
        upsert=True
    )
    
    await log_action("user_banned", callback.from_user.id, app["user_id"])
    
    await bot.send_message(
        app["user_id"],
        "⛔ Вы заблокированы и не можете использовать бота."
    )
    
    await callback.message.edit_caption(
        caption=callback.message.caption + f"\n\n⛔ ЗАБАНЕН ({callback.from_user.username})"
    )
    await callback.answer("⛔ Пользователь забанен")

@router.callback_query(F.data.startswith("vote_"))
async def start_voting(callback: CallbackQuery):
    """Начать голосование"""
    if not await is_admin(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return
    
    app_id = callback.data.split("_")[1]
    
    app = await applications_col.find_one({"_id": app_id})
    if not app:
        await callback.answer("❌ Заявка не найдена", show_alert=True)
        return
    
    vote_text = (
        f"🗳 <b>ГОЛОСОВАНИЕ</b>\n\n"
        f"Игрок <b>{app['answers']['game_nick']}</b> хочет вступить в клан.\n"
        f"Если вы не против 🙂"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Не против (0)", callback_data=f"voteyes_{app_id}"),
            InlineKeyboardButton(text="❌ Против (0)", callback_data=f"voteno_{app_id}")
        ]
    ])
    
    await bot.send_message(GUILD_CHAT_ID, vote_text, reply_markup=keyboard)
    await callback.answer("🗳 Голосование создано")

@router.callback_query(F.data.startswith("voteyes_"))
async def vote_yes(callback: CallbackQuery):
    """Голос ЗА"""
    app_id = callback.data.split("_")[1]
    user_id = callback.from_user.id
    
    app = await applications_col.find_one({"_id": app_id})
    if not app:
        await callback.answer("❌ Заявка не найдена", show_alert=True)
        return
    
    votes_yes = app.get("votes_yes", [])
    votes_no = app.get("votes_no", [])
    
    # Убрать из "против" если был там
    if user_id in votes_no:
        votes_no.remove(user_id)
    
    # Добавить в "за" если еще нет
    if user_id not in votes_yes:
        votes_yes.append(user_id)
    
    await applications_col.update_one(
        {"_id": app_id},
        {"$set": {"votes_yes": votes_yes, "votes_no": votes_no}}
    )
    
    # Обновить кнопки
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=f"✅ Не против ({len(votes_yes)})", callback_data=f"voteyes_{app_id}"),
            InlineKeyboardButton(text=f"❌ Против ({len(votes_no)})", callback_data=f"voteno_{app_id}")
        ]
    ])
    
    await callback.message.edit_reply_markup(reply_markup=keyboard)
    await callback.answer("✅ Ваш голос учтён")

@router.callback_query(F.data.startswith("voteno_"))
async def vote_no(callback: CallbackQuery):
    """Голос ПРОТИВ"""
    app_id = callback.data.split("_")[1]
    user_id = callback.from_user.id
    
    app = await applications_col.find_one({"_id": app_id})
    if not app:
        await callback.answer("❌ Заявка не найдена", show_alert=True)
        return
    
    votes_yes = app.get("votes_yes", [])
    votes_no = app.get("votes_no", [])
    
    # Убрать из "за" если был там
    if user_id in votes_yes:
        votes_yes.remove(user_id)
    
    # Добавить в "против" если еще нет
    if user_id not in votes_no:
        votes_no.append(user_id)
    
    await applications_col.update_one(
        {"_id": app_id},
        {"$set": {"votes_yes": votes_yes, "votes_no": votes_no}}
    )
    
    # Обновить кнопки
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=f"✅ Не против ({len(votes_yes)})", callback_data=f"voteyes_{app_id}"),
            InlineKeyboardButton(text=f"❌ Против ({len(votes_no)})", callback_data=f"voteno_{app_id}")
        ]
    ])
    
    await callback.message.edit_reply_markup(reply_markup=keyboard)
    await callback.answer("❌ Ваш голос учтён")

# ==================== УПРАВЛЕНИЕ ГИЛЬДИЕЙ ====================

@router.message(Command("setguild"))
async def set_guild(message: Message):
    """Установка гильдии (только для владельца бота)"""
    
    # ПРЯМАЯ ПРОВЕРКА ПРАВ (Самая надежная)
    if message.from_user.id != ADMIN_ID:
        await message.answer(f"❌ У вас нет прав. Ваш ID: {message.from_user.id}")
        return
    
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer(
            "📍 **Инструкция:**\n"
            "Напишите: `/setguild <URL>`\n\n"
            "Пример:\n`/setguild https://rucoyonline.com/guild/IOT`",
            parse_mode="Markdown"
        )
        return
    
    url = args[1].strip()
    await message.answer("⏳ **Начинаю парсинг...**\nПожалуйста, подождите.")
    
    try:
        # Предполагаем, что функция parse_guild_page уже определена в твоем коде
        guild_data = await parse_guild_page(url)
        
        if not guild_data:
            await message.answer("❌ Ошибка: Не удалось получить данные с сайта. Проверьте ссылку.")
            return

        # ПРИВЯЗКА ЧАТА И ТЕМЫ (Чтобы бот знал, куда слать заявки)
        guild_data["chat_id"] = message.chat.id
        guild_data["topic_id"] = message.message_thread_id if message.is_topic_message else None
        guild_data["updated_at"] = datetime.now()

        # Сохранение в MongoDB (guild_col должна быть определена ранее)
        await guild_col.update_one(
            {}, 
            {"$set": guild_data}, 
            upsert=True
        )
        
        await log_action("guild_set", message.from_user.id, details={"url": url, "name": guild_data.get('name')})
        
        await message.answer(
            f"✅ **ГИЛЬДИЯ ПОДКЛЮЧЕНА!**\n\n"
            f"🏰 Название: <b>{guild_data['name']}</b>\n"
            f"👥 Участников: {len(guild_data['members'])}\n"
            f"📍 Привязано к чату: <code>{message.chat.id}</code>\n"
            f"🔗 URL: {url}",
            parse_mode="HTML"
        )
    except Exception as e:
        await message.answer(f"❌ Произошла техническая ошибка: {e}")

@router.callback_query(F.data == "guild_info")
async def show_guild_info(callback: CallbackQuery):
    """Информация о текущей гильдии из базы данных"""
    guild_data = await guild_col.find_one()
    
    if not guild_data:
        await callback.answer("⚠️ Гильдия еще не настроена админом.", show_alert=True)
        return
    
    members = guild_data.get("members", [])
    total_level = sum(m.get("level", 0) for m in members)
    avg_level = total_level // len(members) if members else 0
    
    # Считаем неактивных (если есть поле last_seen)
    inactive_threshold = datetime.now() - timedelta(days=7)
    inactive_count = 0
    for m in members:
        ls = m.get("last_seen")
        if ls and isinstance(ls, datetime) and ls < inactive_threshold:
            inactive_count += 1
    
    text = (
        f"🏰 <b>ИНФОРМАЦИЯ О ГИЛЬДИИ: {guild_data['name']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Участников: <b>{len(members)}</b>\n"
        f"📊 Суммарный lvl: <b>{total_level}</b>\n"
        f"📈 Средний lvl: <b>{avg_level}</b>\n"
        f"🟡 Неактив (>7дн): <b>{inactive_count}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🕒 Последнее обновление: {guild_data.get('updated_at', 'Неизвестно').strftime('%H:%M %d.%m')}"
    )
    
    # get_main_keyboard — твоя функция клавиатуры
    await callback.message.edit_text(text, reply_markup=get_main_keyboard(), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "guild_members")
async def show_guild_members(callback: CallbackQuery):
    """Список участников гильдии"""
    guild_data = await guild_col.find_one()
    
    if not guild_data:
        await callback.answer("❌ Гильдия не настроена", show_alert=True)
        return
    
    members = sorted(guild_data.get("members", []), key=lambda x: x["level"], reverse=True)
    inactive_threshold = datetime.now() - timedelta(days=7)
    
    text = f"👥 <b>Участники гильдии {guild_data['name']}</b>\n\n"
    
    for m in members[:30]:  # Показываем первых 30
        icon = "⭐" if m.get("is_leader") else ""
        last_seen = m.get("last_seen", datetime.now())
        status = "🟢" if last_seen > inactive_threshold else "🟡"
        
        text += f"{icon}{status} <b>{m['nick']}</b> — ур. {m['level']}\n"
    
    if len(members) > 30:
        text += f"\n... и еще {len(members) - 30} участников"
    
    await callback.message.edit_text(text, reply_markup=get_main_keyboard())
    await callback.answer()

@router.callback_query(F.data == "stats")
async def show_stats(callback: CallbackQuery):
    """Статистика гильдии"""
    guild_data = await guild_col.find_one()
    
    if not guild_data:
        await callback.answer("❌ Гильдия не настроена", show_alert=True)
        return
    
    members = guild_data.get("members", [])
    total_level = sum(m["level"] for m in members)
    avg_level = total_level // len(members) if members else 0
    leaders = [m for m in members if m.get("is_leader")]
    
    inactive_threshold = datetime.now() - timedelta(days=7)
    inactive = [m for m in members if m.get("last_seen", datetime.now()) < inactive_threshold]
    
    top_players = sorted(members, key=lambda x: x["level"], reverse=True)[:10]
    
    text = (
        f"📊 <b>Статистика гильдии {guild_data['name']}</b>\n\n"
        f"👥 Всего участников: {len(members)}\n"
        f"📊 Суммарный уровень: {total_level}\n"
        f"📈 Средний уровень: {avg_level}\n"
        f"👑 Лидеров: {len(leaders)}\n"
        f"🟡 Неактивных: {len(inactive)}\n\n"
        f"🏆 <b>Топ-10 по уровням:</b>\n"
    )
    
    for i, p in enumerate(top_players, 1):
        icon = "⭐" if p.get("is_leader") else ""
        text += f"{i}. {icon}<b>{p['nick']}</b> — {p['level']}\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

# ==================== УПРАВЛЕНИЕ ЛИДЕРАМИ ====================

@router.callback_query(F.data == "admin_leaders")
async def manage_leaders(callback: CallbackQuery):
    """Управление лидерами"""
    if not await is_admin(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return
    
    guild_data = await guild_col.find_one()
    if not guild_data:
        await callback.answer("❌ Гильдия не настроена", show_alert=True)
        return
    
    leaders = [m for m in guild_data.get("members", []) if m.get("is_leader")]
    
    text = "👑 <b>Управление лидерами</b>\n\n"
    
    if leaders:
        text += "<b>Текущие лидеры:</b>\n"
        for l in leaders:
            text += f"⭐ {l['nick']} — ур. {l['level']}\n"
    else:
        text += "Лидеров пока нет\n"
    
    text += "\n💡 Используйте команды:\n"
    text += "/addleader <ник> — назначить лидера\n"
    text += "/removeleader <ник> — снять лидера"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Админ-панель", callback_data="admin_panel")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

@router.message(Command("addleader"))
async def add_leader(message: Message):
    """Добавить лидера"""
    if not await is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав для этой команды")
        return
    
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: /addleader <ник игрока>")
        return
    
    nick = args[1].strip()
    
    result = await guild_col.update_one(
        {"members.nick": nick},
        {"$set": {"members.$.is_leader": True}}
    )
    
    if result.modified_count > 0:
        await log_action("leader_added", message.from_user.id, details={"nick": nick})
        await message.answer(f"✅ Игрок <b>{nick}</b> назначен лидером")
    else:
        await message.answer(f"❌ Игрок <b>{nick}</b> не найден в гильдии")

@router.message(Command("removeleader"))
async def remove_leader(message: Message):
    """Убрать лидера"""
    if not await is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав для этой команды")
        return
    
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: /removeleader <ник игрока>")
        return
    
    nick = args[1].strip()
    
    result = await guild_col.update_one(
        {"members.nick": nick},
        {"$set": {"members.$.is_leader": False}}
    )
    
    if result.modified_count > 0:
        await log_action("leader_removed", message.from_user.id, details={"nick": nick})
        await message.answer(f"✅ С игрока <b>{nick}</b> снята роль лидера")
    else:
        await message.answer(f"❌ Игрок <b>{nick}</b> не найден в гильдии")

# ==================== WEBHOOK ДЛЯ RENDER ====================


# ==================== ФУНКЦИИ СТАРТАПА ====================

async def on_startup(dispatcher: Dispatcher, bot: Bot):
    """Действия при запуске сервера"""
    logger.info("Запуск процесса Startup...")
    
    # Настройка Webhook
    if WEBHOOK_URL:
        webhook_path = f"/{BOT_TOKEN}"
        url = f"{WEBHOOK_URL}{webhook_path}"
        await bot.set_webhook(url)
        logger.info(f"Webhook установлен: {url}")
    else:
        logger.warning("WEBHOOK_URL не задан! Бот может не получать сообщения.")

    # Запуск планировщика задач
    if not scheduler.running:
        # Добавляем задачи (проверь, что функции update_guild_data и check_inactive_members созданы)
        scheduler.add_job(update_guild_data, "interval", minutes=10)
        scheduler.add_job(check_inactive_members, "interval", hours=12)
        scheduler.start()
        logger.info("Планировщик задач запущен.")

# ==================== ГЛАВНЫЙ БЛОК ЗАПУСКА ====================

def main():
    """Точка входа для Render (aiohttp server)"""
    
    # 1. Создаем веб-приложение
    app = web.Application()

    # 2. Создаем обработчик запросов от Telegram
    webhook_requests_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot
    )
    
    # 3. Регистрируем путь для вебхука (должен совпадать с URL в set_webhook)
    webhook_requests_handler.register(app, path=f"/{BOT_TOKEN}")

    # 4. Настраиваем связи между приложением, диспетчером и ботом
    setup_application(app, dp, bot=bot)
    
    # 5. Регистрируем событие запуска
    dp.startup.register(on_startup)

    # 6. Запускаем сервер
    logger.info(f"Сервер запускается на порту {PORT}")
    web.run_app(app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен вручную")
    except Exception as e:
        logger.error(f"Критическая ошибка при запуске: {e}")
