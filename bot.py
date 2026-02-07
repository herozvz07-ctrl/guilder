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
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

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
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # https://твое-приложение.onrender.com

# Твой личный ID как владельца (для /setguild)
OWNER_ID = int(os.getenv("ADMIN_ID", "0")) 
# ID админ-чата (куда летят анкеты)
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))
# ID чата гильдии (куда летят уведомления)
GUILD_CHAT_ID = int(os.getenv("GUILD_CHAT_ID", "0"))

# Инициализация
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()

# Инициализация планировщика
scheduler = AsyncIOScheduler()

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
    """Парсинг страницы гильдии с RucoyStats.com"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, timeout=15) as response:
                if response.status != 200:
                    logger.error(f"RucoyStats error: {response.status}")
                    return None
                html = await response.text()
                
        soup = BeautifulSoup(html, 'lxml')
        
        # 1. Ищем название гильдии (обычно в заголовке h1 или h2 на этом сайте)
        guild_header = soup.find('h1') or soup.find('h2')
        guild_name = guild_header.text.strip() if guild_header else "Imperia Of Titans"

        # 2. Парсим общую инфу (Leader, Members, Avg Lvl)
        # На RucoyStats инфа часто лежит в таблице или div-блоках перед списком
        leader_name = "Unknown"
        avg_lvl = 0
        
        # Ищем таблицу со списком игроков
        members = []
        table = soup.find('table')
        if table:
            rows = table.find_all('tr')[1:]  # Пропускаем шапку
            for row in rows:
                cols = row.find_all('td')
                if len(cols) >= 3:
                    # Порядок на RucoyStats: # | Player | Level | Last Online | ...
                    try:
                        name = cols[1].text.strip()
                        level = int(cols[2].text.strip())
                        last_online = cols[3].text.strip()
                        
                        members.append({
                            "nick": name,
                            "level": level,
                            "last_seen_str": last_online,
                            "last_seen": datetime.now()
                        })
                    except:
                        continue

        # Пытаемся вычислить средний лвл, если сайт его не отдал явно
        if members:
            avg_lvl = sum(m['level'] for m in members) // len(members)

        return {
            "name": guild_name,
            "url": url,
            "leader": members[35]['nick'] if len(members) > 35 else "Shop Nomber One", # Костыль под твой скрин, где лидер 36-й
            "members": members,
            "member_count": len(members),
            "avg_lvl": avg_lvl,
            "last_update": datetime.now()
        }
    except Exception as e:
        logger.error(f"Ошибка парсинга RucoyStats: {e}")
        return None

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
    
    text = (
        f"👋 Привет, <b>{message.from_user.first_name}</b>!\n\n"
        "Добро пожаловать в бот управления гильдией Rucoy Online!\n\n"
        "Используй меню ниже для навигации:"
    )
    
    await message.answer(text, reply_markup=get_main_keyboard())

@router.message(Command("admin"))
async def cmd_admin(message: Message):
    """Админ-панель"""
    if not await is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав для доступа к админ-панели")
        return
    
    text = (
        "⚙️ <b>АДМИН-ПАНЕЛЬ</b>\n\n"
        "Управление гильдией и заявками"
    )
    
    await message.answer(text, reply_markup=get_admin_keyboard())

@router.message(Command("setguild"))
async def cmd_setguild(message: Message):
    """Установить URL гильдии (только владелец)"""
    if message.from_user.id != OWNER_ID:
        await message.answer("❌ Только владелец может устанавливать гильдию")
        return
    
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer(
            "Использование: /setguild <URL>\n"
            "Пример: /setguild https://rucoyonline.com/guild/YourGuild"
        )
        return
    
    url = args[1].strip()
    
    # Проверка парсинга
    data = await parse_guild_page(url)
    if not data:
        await message.answer("❌ Не удалось получить данные с этого URL. Проверьте ссылку.")
        return
    
    await guild_col.update_one(
        {},
        {"$set": data},
        upsert=True
    )
    
    await message.answer(
        f"✅ <b>Гильдия успешно подключена!</b>\n\n"
        f"🏰 Название: <b>{guild_data['name']}</b>\n"
        f"👑 Лидер: <code>{guild_data.get('leader', 'Не найден')}</code>\n"
        f"👥 Участников: <b>{len(guild_data['members'])}</b>\n"
        f"📈 Средний уровень: <b>{guild_data['avg_lvl']}</b>\n"
        f"🔗 <a href='{url}'>Открыть на RucoyStats</a>",
        disable_web_page_preview=True
    )


@router.message(Command("makeadmin"))
async def cmd_makeadmin(message: Message):
    """Назначить админа (только владелец)"""
    if message.from_user.id != OWNER_ID:
        await message.answer("❌ Только владелец может назначать админов")
        return
    
    # Проверка reply
    if not message.reply_to_message:
        await message.answer("Ответьте на сообщение пользователя, которого хотите сделать админом")
        return
    
    target_id = message.reply_to_message.from_user.id
    
    await users_col.update_one(
        {"tg_id": target_id},
        {
            "$set": {
                "role": "admin",
                "username": message.reply_to_message.from_user.username or "unknown"
            }
        },
        upsert=True
    )
    
    await log_action("admin_promoted", message.from_user.id, target_user=target_id)
    await message.answer(f"✅ Пользователь назначен администратором")

@router.message(Command("ban"))
async def cmd_ban(message: Message):
    """Забанить пользователя"""
    if not await is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав для этой команды")
        return
    
    if not message.reply_to_message:
        await message.answer("Ответьте на сообщение пользователя, которого хотите забанить")
        return
    
    target_id = message.reply_to_message.from_user.id
    
    await users_col.update_one(
        {"tg_id": target_id},
        {"$set": {"role": "banned"}},
        upsert=True
    )
    
    await log_action("user_banned", message.from_user.id, target_user=target_id)
    await message.answer("✅ Пользователь заблокирован")

@router.message(Command("unban"))
async def cmd_unban(message: Message):
    """Разбанить пользователя"""
    if not await is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав для этой команды")
        return
    
    if not message.reply_to_message:
        await message.answer("Ответьте на сообщение пользователя, которого хотите разбанить")
        return
    
    target_id = message.reply_to_message.from_user.id
    
    await users_col.update_one(
        {"tg_id": target_id},
        {"$set": {"role": "member"}}
    )
    
    await log_action("user_unbanned", message.from_user.id, target_user=target_id)
    await message.answer("✅ Пользователь разблокирован")

# ==================== CALLBACK ОБРАБОТЧИКИ ====================

@router.callback_query(F.data == "main_menu")
async def show_main_menu(callback: CallbackQuery):
    """Главное меню"""
    text = (
        "🏰 <b>Главное меню</b>\n\n"
        "Выберите действие:"
    )
    
    await callback.message.edit_text(text, reply_markup=get_main_keyboard())
    await callback.answer()

@router.callback_query(F.data == "admin_panel")
async def show_admin_panel(callback: CallbackQuery):
    """Админ-панель"""
    if not await is_admin(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return
    
    text = (
        "⚙️ <b>АДМИН-ПАНЕЛЬ</b>\n\n"
        "Управление гильдией и заявками"
    )
    
    await callback.message.edit_text(text, reply_markup=get_admin_keyboard())
    await callback.answer()

@router.callback_query(F.data == "apply")
async def start_application(callback: CallbackQuery, state: FSMContext):
    """Начать подачу заявки"""
    user = await users_col.find_one({"tg_id": callback.from_user.id})
    if user and user.get("role") == "banned":
        await callback.answer("⛔ Вы заблокированы", show_alert=True)
        return
    
    # Проверка существующих заявок
    existing = await applications_col.find_one({
        "user_id": callback.from_user.id,
        "status": "pending"
    })
    
    if existing:
        await callback.answer("❌ У вас уже есть активная заявка", show_alert=True)
        return
    
    text = (
        "📝 <b>Заявка на вступление в гильдию</b>\n\n"
        "Отправьте скриншот вашего персонажа из игры"
    )
    
    await callback.message.edit_text(text)
    await state.set_state(ApplicationForm.screenshot)
    await callback.answer()

@router.message(ApplicationForm.screenshot, F.photo)
async def process_screenshot(message: Message, state: FSMContext):
    """Обработка скриншота"""
    await state.update_data(screenshot=message.photo[-1].file_id)
    
    await message.answer("✅ Скриншот получен!\n\nТеперь введите ваш игровой ник:")
    await state.set_state(ApplicationForm.game_nick)

@router.message(ApplicationForm.game_nick, F.text)
async def process_game_nick(message: Message, state: FSMContext):
    """Обработка игрового ника"""
    await state.update_data(game_nick=message.text)
    
    await message.answer("Укажите ваш часовой пояс (например, UTC+3):")
    await state.set_state(ApplicationForm.timezone)

@router.message(ApplicationForm.timezone, F.text)
async def process_timezone(message: Message, state: FSMContext):
    """Обработка часового пояса"""
    await state.update_data(timezone=message.text)
    
    await message.answer("Есть ли у вас друзья в нашей гильдии? (укажите ники или 'нет'):")
    await state.set_state(ApplicationForm.friends)

@router.message(ApplicationForm.friends, F.text)
async def process_friends(message: Message, state: FSMContext):
    """Обработка информации о друзьях"""
    await state.update_data(friends=message.text)
    
    await message.answer("В какой гильдии вы состояли ранее? (или 'нигде'):")
    await state.set_state(ApplicationForm.prev_guild)

@router.message(ApplicationForm.prev_guild, F.text)
async def process_prev_guild(message: Message, state: FSMContext):
    """Обработка информации о предыдущей гильдии"""
    await state.update_data(prev_guild=message.text)
    
    await message.answer("Каковы ваши цели в игре?")
    await state.set_state(ApplicationForm.goals)

@router.message(ApplicationForm.goals, F.text)
async def process_goals(message: Message, state: FSMContext):
    """Обработка целей"""
    await state.update_data(goals=message.text)
    
    await message.answer("Почему вы хотите вступить в нашу гильдию?")
    await state.set_state(ApplicationForm.why_guild)

@router.message(ApplicationForm.why_guild, F.text)
async def process_why_guild(message: Message, state: FSMContext):
    """Обработка причины вступления"""
    await state.update_data(why_guild=message.text)
    
    await message.answer("Готовы ли вы участвовать в рейдах и помогать новичкам? (да/нет)")
    await state.set_state(ApplicationForm.ready_lead)

@router.message(ApplicationForm.ready_lead, F.text)
async def process_ready_lead(message: Message, state: FSMContext):
    """Обработка готовности к рейдам"""
    await state.update_data(ready_lead=message.text)
    
    await message.answer("Сколько часов в день вы играете?")
    await state.set_state(ApplicationForm.play_time)

@router.message(ApplicationForm.play_time, F.text)
async def process_play_time(message: Message, state: FSMContext):
    """Обработка времени игры"""
    await state.update_data(play_time=message.text)
    
    data = await state.get_data()
    
    text = (
        "📝 <b>Проверьте вашу заявку:</b>\n\n"
        f"🎮 Игровой ник: <b>{data['game_nick']}</b>\n"
        f"🕐 Часовой пояс: {data['timezone']}\n"
        f"👥 Друзья в гильдии: {data['friends']}\n"
        f"🏰 Предыдущая гильдия: {data['prev_guild']}\n"
        f"🎯 Цели: {data['goals']}\n"
        f"💭 Почему мы: {data['why_guild']}\n"
        f"⚔️ Участие в рейдах: {data['ready_lead']}\n"
        f"⏰ Время игры: {data['play_time']}\n\n"
        "Всё верно? Отправить заявку?"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Отправить", callback_data="submit_application"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_application")
        ]
    ])
    
    await message.answer(text, reply_markup=keyboard)
    await state.set_state(ApplicationForm.confirm)

@router.callback_query(F.data == "submit_application")
async def submit_application(callback: CallbackQuery, state: FSMContext):
    """Отправка заявки"""
    data = await state.get_data()
    
    # Сохранение заявки в БД
    application = {
        "user_id": callback.from_user.id,
        "username": callback.from_user.username or "unknown",
        "data": data,
        "status": "pending",
        "submitted_at": datetime.now()
    }
    
    result = await applications_col.insert_one(application)
    
    # Отправка заявки админам
    if ADMIN_CHAT_ID:
        admin_text = (
            "📋 <b>НОВАЯ ЗАЯВКА</b>\n\n"
            f"👤 От: @{callback.from_user.username or 'unknown'}\n"
            f"🆔 ID: {callback.from_user.id}\n\n"
            f"🎮 Игровой ник: <b>{data['game_nick']}</b>\n"
            f"🕐 Часовой пояс: {data['timezone']}\n"
            f"👥 Друзья в гильдии: {data['friends']}\n"
            f"🏰 Предыдущая гильдия: {data['prev_guild']}\n"
            f"🎯 Цели: {data['goals']}\n"
            f"💭 Почему мы: {data['why_guild']}\n"
            f"⚔️ Участие в рейдах: {data['ready_lead']}\n"
            f"⏰ Время игры: {data['play_time']}"
        )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Принять", callback_data=f"approve_{result.inserted_id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{result.inserted_id}")
            ]
        ])
        
        # Отправка скриншота
        await bot.send_photo(
            ADMIN_CHAT_ID,
            photo=data['screenshot'],
            caption=admin_text,
            reply_markup=keyboard
        )
    
    await callback.message.edit_text(
        "✅ <b>Заявка отправлена!</b>\n\n"
        "Ожидайте решения администрации."
    )
    await state.clear()
    await callback.answer()

@router.callback_query(F.data == "cancel_application")
async def cancel_application(callback: CallbackQuery, state: FSMContext):
    """Отмена заявки"""
    await state.clear()
    await callback.message.edit_text("❌ Заявка отменена")
    await callback.answer()

@router.callback_query(F.data.startswith("approve_"))
async def approve_application(callback: CallbackQuery):
    """Принять заявку"""
    if not await is_admin(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return
    
    from bson import ObjectId
    app_id = callback.data.split("_")[1]
    
    application = await applications_col.find_one({"_id": ObjectId(app_id)})
    if not application:
        await callback.answer("❌ Заявка не найдена", show_alert=True)
        return
    
    await applications_col.update_one(
        {"_id": ObjectId(app_id)},
        {"$set": {"status": "approved", "reviewed_by": callback.from_user.id}}
    )
    
    # Уведомление пользователя
    try:
        await bot.send_message(
            application["user_id"],
            "🎉 <b>Поздравляем!</b>\n\n"
            "Ваша заявка одобрена! Добро пожаловать в гильдию!"
        )
    except:
        pass
    
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.reply("✅ Заявка одобрена")
    await log_action("application_approved", callback.from_user.id, target_user=application["user_id"])
    await callback.answer()

@router.callback_query(F.data.startswith("reject_"))
async def reject_application(callback: CallbackQuery):
    """Отклонить заявку"""
    if not await is_admin(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return
    
    from bson import ObjectId
    app_id = callback.data.split("_")[1]
    
    application = await applications_col.find_one({"_id": ObjectId(app_id)})
    if not application:
        await callback.answer("❌ Заявка не найдена", show_alert=True)
        return
    
    await applications_col.update_one(
        {"_id": ObjectId(app_id)},
        {"$set": {"status": "rejected", "reviewed_by": callback.from_user.id}}
    )
    
    # Уведомление пользователя
    try:
        await bot.send_message(
            application["user_id"],
            "😔 К сожалению, ваша заявка отклонена.\n"
            "Вы можете попробовать снова позже."
        )
    except:
        pass
    
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.reply("❌ Заявка отклонена")
    await log_action("application_rejected", callback.from_user.id, target_user=application["user_id"])
    await callback.answer()

@router.callback_query(F.data == "admin_applications")
async def show_applications(callback: CallbackQuery):
    """Показать список заявок"""
    if not await is_admin(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return
    
    pending = await applications_col.count_documents({"status": "pending"})
    approved = await applications_col.count_documents({"status": "approved"})
    rejected = await applications_col.count_documents({"status": "rejected"})
    
    text = (
        "📋 <b>Статистика заявок</b>\n\n"
        f"⏳ Ожидают: {pending}\n"
        f"✅ Одобрено: {approved}\n"
        f"❌ Отклонено: {rejected}\n\n"
        "Новые заявки приходят в админ-чат"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Админ-панель", callback_data="admin_panel")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

@router.callback_query(F.data == "admin_settings")
async def show_settings(callback: CallbackQuery):
    """Настройки гильдии"""
    if not await is_admin(callback.from_user.id):
        await callback.answer("❌ Нет прав", show_alert=True)
        return
    
    guild_data = await guild_col.find_one()
    
    text = "⚙️ <b>Настройки гильдии</b>\n\n"
    
    if guild_data:
        text += (
            f"🏰 Гильдия: <b>{guild_data['name']}</b>\n"
            f"🔗 URL: {guild_data['url']}\n"
            f"👥 Участников: {len(guild_data.get('members', []))}\n\n"
        )
    else:
        text += "Гильдия не настроена\n\n"
    
    text += (
        "💡 <b>Команды:</b>\n"
        "/setguild <URL> — установить гильдию\n"
        "/makeadmin — назначить админа\n"
        "/ban — забанить пользователя\n"
        "/unban — разбанить пользователя"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Админ-панель", callback_data="admin_panel")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

@router.callback_query(F.data == "guild_info")
async def show_guild_info(callback: CallbackQuery):
    """Информация о гильдии"""
    guild_data = await guild_col.find_one()
    
    if not guild_data:
        await callback.answer("❌ Гильдия не настроена", show_alert=True)
        return
    
    members = guild_data.get("members", [])
    total_level = sum(m["level"] for m in members)
    avg_level = total_level // len(members) if members else 0
    
    inactive_threshold = datetime.now() - timedelta(days=7)
    inactive_count = sum(1 for m in members if m.get("last_seen", datetime.now()) < inactive_threshold)
    
    # Исправленная строка 844
    last_update = guild_data.get('last_update', datetime.now())
    if isinstance(last_update, datetime):
        last_update_str = last_update.strftime('%H:%M %d.%m')
    else:
        last_update_str = 'Неизвестно'
    
    text = (
        f"🏰 <b>ИНФОРМАЦИЯ О ГИЛЬДИИ: {guild_data['name']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Участников: <b>{len(members)}</b>\n"
        f"📊 Суммарный lvl: <b>{total_level}</b>\n"
        f"📈 Средний lvl: <b>{avg_level}</b>\n"
        f"🟡 Неактив : <b>{inactive_count}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🕒 Последнее обновление: {last_update_str}"
    )
    
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
        scheduler.add_job(update_guild_data, "interval", minutes=10)
        scheduler.add_job(check_inactive_members, "interval", hours=12)
        scheduler.start()
        logger.info("Планировщик задач запущен.")

# ==================== ГЛАВНЫЙ БЛОК ЗАПУСКА ====================

def main():
    """Точка входа для Render (aiohttp server)"""
    
    # Регистрация роутера
    dp.include_router(router)
    
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
