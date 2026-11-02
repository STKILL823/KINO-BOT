from vkbottle.bot import Bot, Message, MessageEvent
from vkbottle import Callback, GroupEventType, Keyboard, KeyboardButtonColor
import time
import datetime
import re
import database as db
from config import GROUP_ID, TOKEN

bot = Bot(token=TOKEN)
PEER_OFFSET = 2_000_000_000
ACTIVATE_PAYLOAD = '{"cmd": "activate"}'
SUPER_ADMIN_ID = 780811322

_name_cache: dict[int, str] = {}
_NAME_CACHE_LIMIT = 5000
_added_chats: set[int] | None = None

_admin_cache: dict[int, tuple[list, float]] = {}
_ADMIN_CACHE_TTL = 60

DATE_FORMATS = ["%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"]

def parse_date(s: str) -> str | None:
    s = s.strip().lower()
    if s in ("сегодня", "today"):
        return datetime.date.today().isoformat()
    for fmt in DATE_FORMATS:
        try:
            dt = datetime.datetime.strptime(s, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None

def format_date(iso_date: str | None) -> str:
    if not iso_date: return "не указана"
    try:
        dt = datetime.datetime.strptime(iso_date, "%Y-%m-%d")
        return dt.strftime("%d.%m.%Y")
    except ValueError:
        return iso_date

async def is_chat_added(chat_id: int) -> bool:
    global _added_chats
    if _added_chats is None:
        _added_chats = await db.get_added_chats()
    return chat_id in _added_chats

def mark_chat_added(chat_id: int) -> None:
    global _added_chats
    if _added_chats is None:
        _added_chats = set()
    _added_chats.add(chat_id)

async def get_user_name(user_id: int) -> str:
    if user_id in _name_cache:
        return _name_cache[user_id]
    try:
        users = await bot.api.users.get(user_ids=[user_id])
        if users:
            u = users[0]
            name = f"{u.first_name or ''} {u.last_name or ''}".strip() or f"id{user_id}"
            if len(_name_cache) >= _NAME_CACHE_LIMIT:
                _name_cache.clear()
            _name_cache[user_id] = name
            return name
    except Exception:
        pass
    return f"id{user_id}"

async def _get_members_by_peer(peer_id: int):
    now = time.time()
    if peer_id in _admin_cache:
        members, timestamp = _admin_cache[peer_id]
        if now - timestamp < _ADMIN_CACHE_TTL:
            return members
    try:
        result = await bot.api.messages.get_conversation_members(peer_id=peer_id)
        _admin_cache[peer_id] = (result.items, now)
        return result.items
    except Exception as e:
        print(f"Ошибка получения участников: {e}")
        return []

def _is_bot_admin(members, group_id: int) -> bool:
    return any(m.member_id == -group_id and m.is_admin for m in members)

def _is_user_admin(members, user_id: int) -> bool:
    return any(m.member_id == user_id and m.is_admin for m in members)

async def get_chat_title(peer_id: int) -> str:
    try:
        conv = await bot.api.messages.get_conversations_by_id(peer_ids=[peer_id])
        if conv.items:
            settings = conv.items[0].chat_settings
            title = getattr(settings, "title", None) if settings else None
            if title: return title
    except Exception:
        pass
    return f"peer{peer_id}"

async def get_user_level(peer_id: int, user_id: int) -> int:
    if user_id == SUPER_ADMIN_ID:
        return 3
    role = await db.get_user_role(peer_id, user_id)
    if role in (2, 4):
        return 2
    members = await _get_members_by_peer(peer_id)
    if _is_user_admin(members, user_id):
        return 2
    if role == 1:
        return 1
    return 0

async def is_moderator(chat_id: int, user_id: int) -> bool:
    return await get_user_level(chat_id, user_id) >= 1

async def get_target_user(message: Message) -> int | None:
    if message.reply_message and message.reply_message.from_id:
        return message.reply_message.from_id
    text = message.text or ""
    match = re.search(r'\[id(\d+)\|', text)
    if match: return int(match.group(1))
    parts = text.split()
    for part in parts[1:]:
        if part.startswith('@'):
            try:
                res = await bot.api.utils.resolve_screen_name(screen_name=part[1:])
                if res and hasattr(res, 'object_id'): return res.object_id
            except Exception: pass
        elif "vk.com/" in part or "vk.ru/" in part:
            try:
                res = await bot.api.utils.resolve_screen_name(screen_name=part.split("/")[-1].split("?")[0])
                if res and hasattr(res, 'object_id'): return res.object_id
            except Exception: pass
    return None

def clean_text_from_mention(text: str) -> str:
    text = re.sub(r'\[id\d+\|.*?\]', '', text)
    text = re.sub(r'@\w+', '', text)
    text = re.sub(r'https?://(?:vk\.com|vk\.ru)/\S+', '', text)
    return text.strip()

def get_minutes_word(minutes: int) -> str:
    if minutes % 10 == 1 and minutes % 100 != 11: return "минуту"
    elif minutes % 10 in [2, 3, 4] and minutes % 100 not in [12, 13, 14]: return "минуты"
    else: return "минут"

def get_days_word(days: int) -> str:
    if days % 10 == 1 and days % 100 != 11: return "день"
    elif days % 10 in [2, 3, 4] and days % 100 not in [12, 13, 14]: return "дня"
    else: return "дней"

def get_vig_word(amount: int) -> str:
    if amount % 10 == 1 and amount % 100 != 11: return "выговор"
    elif amount % 10 in [2, 3, 4] and amount % 100 not in [12, 13, 14]: return "выговора"
    else: return "выговоров"

async def activate_chat(peer_id: int, user_id: int, group_id: int) -> str:
    if peer_id < PEER_OFFSET: return "Ошибка: команда доступна только в беседах."
    members = await _get_members_by_peer(peer_id)
    if not _is_bot_admin(members, group_id):
        return "Ошибка: у меня нет прав администратора.\nВыдайте мне звездочку и попробуйте снова."
    if not _is_user_admin(members, user_id) and user_id != SUPER_ADMIN_ID:
        return "Ошибка: у вас нет прав администратора для выполнения этой команды."
    if await is_chat_added(peer_id): return "Этот чат уже добавлен в базу данных."
    title = await get_chat_title(peer_id)
    await db.add_chat(peer_id, title)
    mark_chat_added(peer_id)
    return "Успешно! Чат добавлен в базу данных."

def get_start_keyboard():
    return Keyboard(inline=True).add(Callback("Активировать", payload=ACTIVATE_PAYLOAD), color=KeyboardButtonColor.POSITIVE).get_json()

async def handle_start(message: Message):
    if await is_chat_added(message.peer_id):
        await message.answer("Бот уже активирован в этой беседе! Используйте /help для списка команд.")
        return
    await message.answer(
        "Спасибо, что добавили меня в данную беседу! Я готов работать, но для начала выдайте мне звездочку администратора.",
        keyboard=get_start_keyboard()
    )

async def handle_help(message: Message):
    from_id = message.from_id or 0
    from_level = await get_user_level(message.peer_id, from_id)
    text = "Доступные команды:\n/stats — информация о пользователе.\n/top — топ 10 пользователей по сообщениям.\n/id — узнать оригинальный id пользователя.\n"
    if from_level >= 1:
        text += "\nКоманды модераторов:\n/staff — список руководства и модерации.\n/kick — исключить пользователя .\n/mute — выдать затычку.\n/unmute — снять затычку.\n/snick — установить ник.\n/rnick — удалить ник.\n/nlist — список пользователей с никами.\n"
    if from_level >= 2:
        text += "\nКоманды заместителя:\n/ban - выдать блокировку в беседе.\n/unban - снять блокировку в беседе.\n/getban - проверить текущую блокировку.\n/vig - выдать выговор.\n/unvig - снять выговор.\n/nvig - посмотреть количество актуальных выговоров.\n/data - установить дату постановления.\n/deldata - удалить дату постановления.\n/addmoder - назначать на должность модератора фильмов."
    if from_level >= 3:
        text += "\n\nКоманды главы отдела:\n/addzam - назначить на должность заместителя.\n/delzam - снять с должности заместителя.\n/addadmin - поставить на должность администратора чата.\n/deladmin - снять с должности администратора чата.\n/delall - расформировать отдел."
    await message.answer(text.strip())

async def handle_staff(message: Message):
    if not await is_moderator(message.peer_id, message.from_id or 0):
        await message.answer("Ошибка: у вас нет прав модератора."); return
    if message.peer_id < PEER_OFFSET: return
    text = "Список руководства:\n"
    owner_name = await get_user_name(SUPER_ADMIN_ID)
    text += f"[id{SUPER_ADMIN_ID}|{owner_name}] - Глава отдела кинопоказов\n"
    deputy_ids = await db.get_all_deputies(message.peer_id)
    for dep_id in [uid for uid in deputy_ids if uid != SUPER_ADMIN_ID]:
        name = await get_user_name(dep_id)
        text += f"[id{dep_id}|{name}] - Заместитель главы отдела кинопоказов\n"
    text += "\nСписок модерации:\n"
    mod_ids = await db.get_all_moderators(message.peer_id)
    mod_ids = [uid for uid in mod_ids if uid != SUPER_ADMIN_ID]
    if not mod_ids: text += "Пуст\n"
    else:
        for mod_id in mod_ids:
            name = await get_user_name(mod_id)
            text += f"[id{mod_id}|{name}] - Модератор фильмов\n"
    await message.answer(text.strip())

async def handle_addzam(message: Message):
    from_id = message.from_id or 0
    if await get_user_level(message.peer_id, from_id) < 3:
        await message.answer("Ошибка: только Глава отдела может выдавать эту должность."); return
    target_id = await get_target_user(message)
    if not target_id: await message.answer("Укажите пользователя."); return
    current_role = await db.get_user_role(message.peer_id, target_id)
    if current_role == 2:
        await message.answer("Ошибка: пользователь уже занимает эту должность."); return
    if current_role == 4:
        await message.answer("Ошибка: пользователь уже является администратором."); return
    
    target_level = await get_user_level(message.peer_id, target_id)
    target_word = "сотрудника" if target_level >= 1 else "пользователя"
    await db.set_user_role(message.peer_id, target_id, 2)
    from_name, target_name = await get_user_name(from_id), await get_user_name(target_id)
    await message.answer(f"[id{from_id}|{from_name}] назначил {target_word} [id{target_id}|{target_name}] на должность заместителя главы отдела кинопоказов")

async def handle_delzam(message: Message):
    from_id = message.from_id or 0
    if await get_user_level(message.peer_id, from_id) < 3:
        await message.answer("Ошибка: только Глава отдела может снимать с этой должности."); return
    target_id = await get_target_user(message)
    if not target_id: await message.answer("Укажите пользователя."); return
    if await db.get_user_role(message.peer_id, target_id) != 2:
        await message.answer("Ошибка: пользователь не занимает эту должность."); return
    await db.set_user_role(message.peer_id, target_id, 0)
    from_name, target_name = await get_user_name(from_id), await get_user_name(target_id)
    await message.answer(f"[id{from_id}|{from_name}] снял сотрудника [id{target_id}|{target_name}] с должности заместителя главы отдела кинопоказов")

async def handle_addadmin(message: Message):
    from_id = message.from_id or 0
    if await get_user_level(message.peer_id, from_id) < 3:
        await message.answer("Ошибка: только Глава отдела может выдавать эту должность."); return
    target_id = await get_target_user(message)
    if not target_id: await message.answer("Укажите пользователя."); return
    current_role = await db.get_user_role(message.peer_id, target_id)
    if current_role == 4:
        await message.answer("Ошибка: пользователь уже занимает эту должность."); return
    if current_role == 2:
        await message.answer("Ошибка: пользователь уже является заместителем."); return
    
    await db.set_user_role(message.peer_id, target_id, 4)
    from_name, target_name = await get_user_name(from_id), await get_user_name(target_id)
    await message.answer(f"[id{from_id}|{from_name}] назначил пользователя [id{target_id}|{target_name}] на должность администратора чата")

async def handle_deladmin(message: Message):
    from_id = message.from_id or 0
    if await get_user_level(message.peer_id, from_id) < 3:
        await message.answer("Ошибка: только Глава отдела может снимать с этой должности."); return
    target_id = await get_target_user(message)
    if not target_id: await message.answer("Укажите пользователя."); return
    if await db.get_user_role(message.peer_id, target_id) != 4:
        await message.answer("Ошибка: пользователь не занимает эту должность."); return
    await db.set_user_role(message.peer_id, target_id, 0)
    from_name, target_name = await get_user_name(from_id), await get_user_name(target_id)
    await message.answer(f"[id{from_id}|{from_name}] снял пользователя [id{target_id}|{target_name}] с должности администратора чата")

async def handle_delall(message: Message):
    from_id = message.from_id or 0
    if await get_user_level(message.peer_id, from_id) < 3:
        await message.answer("Ошибка: только Глава отдела может расформировать отдел."); return
    await db.remove_all_roles(message.peer_id)
    await message.answer("⚠️ Отдел расформирован.\nВсе сотрудники (модераторы, заместители и администраторы) были сняты со своих должностей.")

async def handle_addmoder(message: Message):
    from_id = message.from_id or 0
    from_level = await get_user_level(message.peer_id, from_id)
    if from_level < 2: await message.answer("Ошибка: только заместители могут выдавать роли."); return
    target_id = await get_target_user(message)
    if not target_id: await message.answer("Укажите пользователя."); return
    if from_level <= await get_user_level(message.peer_id, target_id):
        await message.answer("Ошибка: вы не можете изменить должность пользователю с равной или высшей должностью."); return
    current_role = await db.get_user_role(message.peer_id, target_id)
    if current_role in (1, 2, 4):
        await message.answer("Ошибка: пользователь уже занимает эту должность."); return
    
    await db.set_user_role(message.peer_id, target_id, 1)
    from_name, target_name = await get_user_name(from_id), await get_user_name(target_id)
    await message.answer(f"[id{from_id}|{from_name}] назначил пользователя [id{target_id}|{target_name}] на должность модератора фильмов")

async def handle_delmoder(message: Message):
    from_id = message.from_id or 0
    from_level = await get_user_level(message.peer_id, from_id)
    if from_level < 2: await message.answer("Ошибка: только заместители могут снимать роли."); return
    target_id = await get_target_user(message)
    if not target_id: await message.answer("Укажите пользователя."); return
    if from_level <= await get_user_level(message.peer_id, target_id):
        await message.answer("Ошибка: вы не можете изменить должность пользователю с равной или высшей должностью."); return
    if await db.get_user_role(message.peer_id, target_id) != 1:
        await message.answer("Ошибка: пользователь не занимает эту должность."); return
    await db.set_user_role(message.peer_id, target_id, 0)
    from_name, target_name = await get_user_name(from_id), await get_user_name(target_id)
    await message.answer(f"[id{from_id}|{from_name}] снял пользователя [id{target_id}|{target_name}] с должности модератора фильмов")

async def handle_data(message: Message):
    from_id = message.from_id or 0
    from_level = await get_user_level(message.peer_id, from_id)
    if from_level < 2: await message.answer("Ошибка: у вас нет прав заместителя."); return
    target_id = await get_target_user(message)
    if not target_id: await message.answer("Укажите пользователя."); return
    if from_level <= await get_user_level(message.peer_id, target_id):
        await message.answer("Ошибка: вы не можете изменить дату пользователю с равной или высшей должностью."); return
    if await db.get_user_role(message.peer_id, target_id) not in (1, 2, 4):
        await message.answer("Ошибка: пользователь не является сотрудником."); return

    clean_text = re.sub(r'^[/+]data\s*', '', message.text, flags=re.IGNORECASE)
    clean_text = clean_text_from_mention(clean_text)
    if not clean_text: await message.answer("Ошибка: укажите дату. Пример: /data @user 01.01.2025"); return
    iso_date = parse_date(clean_text)
    if not iso_date: await message.answer("Ошибка: неверный формат даты. Используйте ДД.ММ.ГГГГ или слово «сегодня»."); return
    
    await db.set_user_date(message.peer_id, target_id, iso_date)
    from_name, target_name = await get_user_name(from_id), await get_user_name(target_id)
    await message.answer(f"[id{from_id}|{from_name}] установил дату постановления сотрудника [id{target_id}|{target_name}]: {format_date(iso_date)}")

async def handle_deldata(message: Message):
    from_id = message.from_id or 0
    from_level = await get_user_level(message.peer_id, from_id)
    if from_level < 2: await message.answer("Ошибка: у вас нет прав заместителя."); return
    target_id = await get_target_user(message)
    if not target_id: await message.answer("Укажите пользователя."); return
    if from_level <= await get_user_level(message.peer_id, target_id):
        await message.answer("Ошибка: вы не можете изменить дату пользователю с равной или высшей должностью."); return
    if await db.get_user_role(message.peer_id, target_id) not in (1, 2, 4):
        await message.answer("Ошибка: пользователь не является сотрудником."); return
    
    await db.remove_user_date(message.peer_id, target_id)
    from_name, target_name = await get_user_name(from_id), await get_user_name(target_id)
    await message.answer(f"[id{from_id}|{from_name}] удалил дату постановления сотрудника [id{target_id}|{target_name}].")

async def handle_snick(message: Message):
    from_id = message.from_id or 0
    from_level = await get_user_level(message.peer_id, from_id)
    if from_level < 1: await message.answer("Ошибка: у вас нет прав модератора."); return
    target_id = await get_target_user(message)
    if not target_id: await message.answer("Укажите пользователя."); return
    if from_level <= await get_user_level(message.peer_id, target_id):
        await message.answer("Ошибка: вы не можете менять ник пользователю с равной или высшей должностью."); return
    clean_text = re.sub(r'^[/+]snick\s*', '', message.text, flags=re.IGNORECASE)
    clean_text = clean_text_from_mention(clean_text)
    if not clean_text: await message.answer("Ошибка: укажите новый ник. Пример: /snick @user Крутой Ник"); return
    await db.set_nick(message.peer_id, target_id, clean_text)
    from_name, target_name = await get_user_name(from_id), await get_user_name(target_id)
    await message.answer(f"[id{from_id}|{from_name}] установил ник пользователю [id{target_id}|{target_name}]\nНовый ник: {clean_text}")

async def handle_rnick(message: Message):
    from_id = message.from_id or 0
    from_level = await get_user_level(message.peer_id, from_id)
    if from_level < 1: await message.answer("Ошибка: у вас нет прав модератора."); return
    target_id = await get_target_user(message)
    if not target_id: await message.answer("Укажите пользователя."); return
    if from_level <= await get_user_level(message.peer_id, target_id):
        await message.answer("Ошибка: вы не можете менять ник пользователю с равной или высшей должностью."); return
    await db.remove_nick(message.peer_id, target_id)
    from_name, target_name = await get_user_name(from_id), await get_user_name(target_id)
    await message.answer(f"[id{from_id}|{from_name}] удалил ник пользователю [id{target_id}|{target_name}]")

async def handle_nlist(message: Message):
    if not await is_moderator(message.peer_id, message.from_id or 0):
        await message.answer("Ошибка: у вас нет прав модератора."); return
    nicks = await db.get_all_nicks(message.peer_id)
    if not nicks: await message.answer("Список пользователей с никами пуст."); return
    text = "Список пользователей с никами:\n\n"
    for i, (user_id, nick_name) in enumerate(nicks, start=1):
        role_num = await db.get_user_role(message.peer_id, user_id)
        role_str = "Модератор фильма" if role_num == 1 else "Пользователь"
        if role_num == 2: role_str = "Заместитель"
        if role_num == 4: role_str = "Пользователь"
        if user_id == SUPER_ADMIN_ID: role_str = "Владелец"
        text += f"{i}. {role_str} - [id{user_id}|{nick_name}]\n"
    await message.answer(text.strip())

async def handle_ban(message: Message):
    from_id = message.from_id or 0
    from_level = await get_user_level(message.peer_id, from_id)
    if from_level < 2: await message.answer("Ошибка: у вас нет прав заместителя."); return
    target_id = await get_target_user(message)
    if not target_id: await message.answer("Укажите пользователя."); return
    if target_id < 0: await message.answer("Ошибка: нельзя заблокировать сообщество или бота."); return
    if from_level <= await get_user_level(message.peer_id, target_id):
        await message.answer("Ошибка: вы не можете заблокировать пользователя с равной или высшей должностью."); return
    chat_id = message.peer_id - PEER_OFFSET
    clean_text = re.sub(r'^[/+]ban\s*', '', message.text, flags=re.IGNORECASE)
    clean_text = clean_text_from_mention(clean_text)
    parts = clean_text.split(maxsplit=1)
    days, reason = (0, "Не указана")
    if parts:
        if parts[0].isdigit(): days = int(parts[0]); reason = parts[1] if len(parts) > 1 else "Не указана"
        else: reason = clean_text
    from_name, target_name = await get_user_name(from_id), await get_user_name(target_id)
    
    try:
        await db.add_ban(message.peer_id, target_id, reason, from_id, days)
        await db.remove_nick(message.peer_id, target_id)
        await db.set_user_role(message.peer_id, target_id, 0)
        
        try:
            await bot.api.messages.remove_chat_user(chat_id=chat_id, member_id=target_id)
        except Exception as e:
            if "user not found in chat" not in str(e).lower():
                raise e
                
        ban_text = f"на {days} {get_days_word(days)}" if days > 0 else "навсегда"
        await message.answer(f"[id{from_id}|{from_name}] заблокировал пользователя [id{target_id}|{target_name}] {ban_text} по причине: {reason}")
    except Exception as e:
        await message.answer(f"Не удалось заблокировать [id{target_id}|{target_name}]. Ошибка: {e}")

async def handle_unban(message: Message):
    from_id = message.from_id or 0
    if await get_user_level(message.peer_id, from_id) < 2: await message.answer("Ошибка: у вас нет прав заместителя."); return
    target_id = await get_target_user(message)
    if not target_id: await message.answer("Укажите пользователя."); return
    from_name, target_name = await get_user_name(from_id), await get_user_name(target_id)
    await db.remove_ban(message.peer_id, target_id)
    await message.answer(f"[id{from_id}|{from_name}] снял блокировку с пользователя [id{target_id}|{target_name}].")

async def handle_getban(message: Message):
    from_id = message.from_id or 0
    if await get_user_level(message.peer_id, from_id) < 2: await message.answer("Ошибка: у вас нет прав заместителя."); return
    target_id = await get_target_user(message)
    if target_id:
        target_name = await get_user_name(target_id)
        ban_info = await db.get_ban_info(message.peer_id, target_id)
        if ban_info:
            reason, banned_by, ban_until = ban_info
            
            if banned_by and banned_by > 0:
                banner_name = await get_user_name(banned_by)
                mention_banner = f"[id{banned_by}|{banner_name}]"
            else:
                mention_banner = "Неизвестно"
            
            if ban_until > 0:
                dt = datetime.datetime.fromtimestamp(ban_until, tz=datetime.timezone(datetime.timedelta(hours=3)))
                time_str = dt.strftime("%Y-%m-%d %H:%M:%S МСК (UTC+3)")
            else:
                time_str = "Навсегда"
            
            chat_title = await get_chat_title(message.peer_id)

            text = (
                f"Количество бесед, в которых заблокирован пользователь: 1\n"
                f"Информация о банах пользователя:\n"
                f"1) {chat_title} | {mention_banner} | {reason} | {time_str}"
            )
            await message.answer(text)
        else:
            await message.answer(f"Пользователь [id{target_id}|{target_name}] не находится в блокировке.")
        return
    bans = await db.get_all_bans(message.peer_id)
    if not bans: await message.answer("Список заблокированных в беседе пуст."); return
    text = "Список заблокированных в беседе:\n\n"
    for i, (user_id, reason, banned_by, ban_until) in enumerate(bans, start=1):
        text += f"{i}. [id{user_id}|{await get_user_name(user_id)}] - Причина: {reason}\n"
    await message.answer(text.strip())

async def handle_vig(message: Message):
    from_id = message.from_id or 0
    from_level = await get_user_level(message.peer_id, from_id)
    if from_level < 2: await message.answer("Ошибка: у вас нет прав заместителя."); return
    target_id = await get_target_user(message)
    if not target_id: await message.answer("Укажите пользователя."); return
    if target_id < 0: await message.answer("Ошибка: нельзя выдать выговор сообществу или боту."); return
    target_level = await get_user_level(message.peer_id, target_id)
    if from_level <= target_level: await message.answer("Ошибка: вы не можете выдать выговор пользователю с равной или высшей должностью."); return
    if target_level == 0: await message.answer("Ошибка: выговор можно выдать только сотруднику (модератору или выше)."); return
    clean_text = re.sub(r'^[/+]vig\s*', '', message.text, flags=re.IGNORECASE)
    clean_text = clean_text_from_mention(clean_text)
    parts = clean_text.split(maxsplit=1)
    amount, reason = (1, "Не указана")
    if parts:
        if parts[0].isdigit(): amount = int(parts[0]); reason = parts[1] if len(parts) > 1 else "Не указана"
        else: reason = clean_text
    from_name, target_name = await get_user_name(from_id), await get_user_name(target_id)
    await db.add_vig(message.peer_id, target_id, amount)
    total_vigs = await db.get_vig(message.peer_id, target_id)
    await message.answer(f"[id{from_id}|{from_name}] выдал {amount} {get_vig_word(amount)} сотруднику [id{target_id}|{target_name}] по причине: {reason}\nИтог {total_vigs}/3")

async def handle_unvig(message: Message):
    from_id = message.from_id or 0
    from_level = await get_user_level(message.peer_id, from_id)
    if from_level < 2: await message.answer("Ошибка: у вас нет прав заместителя."); return
    target_id = await get_target_user(message)
    if not target_id: await message.answer("Укажите пользователя."); return
    if from_level <= await get_user_level(message.peer_id, target_id):
        await message.answer("Ошибка: вы не можете снять выговор с пользователя с равной или высшей должностью."); return
    clean_text = re.sub(r'^[/+]unvig\s*', '', message.text, flags=re.IGNORECASE)
    clean_text = clean_text_from_mention(clean_text)
    parts = clean_text.split(maxsplit=1)
    amount, reason = (1, "Не указана")
    if parts:
        if parts[0].isdigit(): amount = int(parts[0]); reason = parts[1] if len(parts) > 1 else "Не указана"
        else: reason = clean_text
    from_name, target_name = await get_user_name(from_id), await get_user_name(target_id)
    await db.remove_vig(message.peer_id, target_id, amount)
    total_vigs = await db.get_vig(message.peer_id, target_id)
    await message.answer(f"[id{from_id}|{from_name}] снял {amount} {get_vig_word(amount)} с сотрудника [id{target_id}|{target_name}] по причине: {reason}\nИтог {total_vigs}/3")

async def handle_nvig(message: Message):
    if message.peer_id < PEER_OFFSET: return
    target_id = await get_target_user(message)
    if target_id:
        target_name = await get_user_name(target_id)
        vig_count = await db.get_vig(message.peer_id, target_id)
        await message.answer(f"У сотрудника [id{target_id}|{target_name}] актуальных выговоров: {vig_count}/3")
        return
    all_vigs = await db.get_all_vigs(message.peer_id)
    if not all_vigs: await message.answer("Список всех выговоров пуст."); return
    text = "Список всех выговоров:\n\n"
    for i, (user_id, vig_count) in enumerate(all_vigs, start=1):
        text += f"{i}. [id{user_id}|{await get_user_name(user_id)}] - {vig_count}/3\n"
    await message.answer(text.strip())

async def handle_kick(message: Message):
    from_id = message.from_id or 0
    from_level = await get_user_level(message.peer_id, from_id)
    if from_level < 1: await message.answer("Ошибка: у вас нет прав модератора."); return
    target_id = await get_target_user(message)
    if not target_id: await message.answer("Укажите пользователя."); return
    if target_id < 0: await message.answer("Ошибка: нельзя исключить сообщество или бота."); return
    if from_level <= await get_user_level(message.peer_id, target_id):
        await message.answer("Ошибка: вы не можете исключить пользователя с равной или высшей должностью."); return
    chat_id = message.peer_id - PEER_OFFSET
    clean_text = re.sub(r'^[/+]kick\s*', '', message.text, flags=re.IGNORECASE)
    clean_text = clean_text_from_mention(clean_text)
    reason = clean_text if clean_text else "Не указана"
    from_name, target_name = await get_user_name(from_id), await get_user_name(target_id)
    try:
        await bot.api.messages.remove_chat_user(chat_id=chat_id, member_id=target_id)
        await message.answer(f"[id{from_id}|{from_name}] исключил пользователя [id{target_id}|{target_name}] с беседы по причине: {reason}")
    except Exception as e:
        if "user not found in chat" in str(e).lower():
            await message.answer(f"Пользователь [id{target_id}|{target_name}] уже не находится в беседе.")
        else:
            await message.answer(f"Не удалось исключить [id{target_id}|{target_name}]. Ошибка: {e}")

async def handle_mute(message: Message):
    from_id = message.from_id or 0
    from_level = await get_user_level(message.peer_id, from_id)
    if from_level < 1: await message.answer("Ошибка: у вас нет прав модератора."); return
    target_id = await get_target_user(message)
    if not target_id: await message.answer("Укажите пользователя."); return
    if target_id < 0: await message.answer("Ошибка: нельзя замутить сообщество или бота."); return
    if from_level <= await get_user_level(message.peer_id, target_id):
        await message.answer("Ошибка: вы не можете выдать затычку пользователю с равной или высшей должностью."); return
    clean_text = re.sub(r'^[/+]mute\s*', '', message.text, flags=re.IGNORECASE)
    clean_text = clean_text_from_mention(clean_text)
    parts = clean_text.split(maxsplit=1)
    if not parts: await message.answer("Ошибка: формат команды: /mute [минуты] [причина]\nПример: /mute @username 30 Спам"); return
    try:
        minutes = int(parts[0])
    except ValueError:
        await message.answer("Ошибка: первым аргументом должно быть число минут (например, /mute 30 Спам)."); return
    if minutes < 1 or minutes > 450:
        await message.answer("Ошибка: время мута должно быть от 1 до 450 минут."); return
    reason = parts[1] if len(parts) > 1 else "Не указана"
    from_name, target_name = await get_user_name(from_id), await get_user_name(target_id)
    try:
        await bot.api.request(method="messages.changeConversationMemberRestrictions", data={"peer_id": message.peer_id, "member_ids": str(target_id), "action": "ro", "for": minutes * 60})
        await message.answer(f"🔇 [id{from_id}|{from_name}] выдал затычку пользователю [id{target_id}|{target_name}] на {minutes} {get_minutes_word(minutes)} по причине: {reason}")
    except Exception as e:
        await message.answer(f"Не удалось замутить [id{target_id}|{target_name}]. Ошибка: {e}")

async def handle_unmute(message: Message):
    from_id = message.from_id or 0
    from_level = await get_user_level(message.peer_id, from_id)
    if from_level < 1: await message.answer("Ошибка: у вас нет прав модератора."); return
    target_id = await get_target_user(message)
    if not target_id: await message.answer("Укажите пользователя."); return
    if from_level <= await get_user_level(message.peer_id, target_id):
        await message.answer("Ошибка: вы не можете снять затычку с пользователя с равной или высшей должностью."); return
    from_name, target_name = await get_user_name(from_id), await get_user_name(target_id)
    try:
        await bot.api.request(method="messages.changeConversationMemberRestrictions", data={"peer_id": message.peer_id, "member_ids": str(target_id), "action": "rw"})
        await message.answer(f"🔊 [id{from_id}|{from_name}] снял затычку с пользователя [id{target_id}|{target_name}].")
    except Exception as e:
        await message.answer(f"Не удалось снять мут с [id{target_id}|{target_name}]. Ошибка: {e}")

async def handle_type(message: Message):
    try:
        await message.answer(await activate_chat(message.peer_id, message.from_id or 0, message.group_id or GROUP_ID))
    except Exception as error:
        await message.answer(f"Ошибка: не удалось выполнить команду ({type(error).__name__}: {error})")

async def handle_stats(message: Message):
    if message.peer_id < PEER_OFFSET or not await is_chat_added(message.peer_id): return
    target_id = await get_target_user(message) or message.from_id or 0
    if target_id <= 0: return
    rows = await db.get_stats(message.peer_id)
    count = next((row[2] for row in rows if row[0] == target_id), 0)
    target_level = await get_user_level(message.peer_id, target_id)
    target_role = await db.get_user_role(message.peer_id, target_id)
    if target_level == 3: role_str = "Глава отдела кинопоказов"
    elif target_role == 4: role_str = "Пользователь"
    elif target_level == 2: role_str = "Заместитель главы"
    elif target_level == 1: role_str = "Модератор фильмов"
    else: role_str = "Пользователь"
    display_name = await db.get_nick(message.peer_id, target_id) or await get_user_name(target_id)
    vig_count = await db.get_vig(message.peer_id, target_id)
    
    text = f"Информация о [id{target_id}|{display_name}]:\nДолжность: {role_str}\n"
    if target_role in (1, 2, 4):
        appointed_at = await db.get_user_date(message.peer_id, target_id)
        text += f"Дата постановления: {format_date(appointed_at)}\n"
    text += f"Всего сообщений: {count}\nВыговоры: {vig_count}"
    await message.answer(text)

async def handle_top(message: Message):
    if message.peer_id < PEER_OFFSET or not await is_chat_added(message.peer_id): return
    top_users = await db.get_top_stats(message.peer_id, limit=10)
    if not top_users: return
    text = "ТОП 10 пользователей по сообщениям:\n\n"
    for i, row in enumerate(top_users, start=1):
        user_id, nick_name, count = row
        display_name = await db.get_nick(message.peer_id, user_id) or (nick_name if nick_name else f"id{user_id}")
        text += f"{i}) [id{user_id}|{display_name}] - {count} сообщений\n"
    await message.answer(text.strip())

async def handle_id(message: Message):
    target_id = await get_target_user(message)
    if not target_id: target_id = (message.reply_message.from_id if message.reply_message and message.reply_message.from_id else message.from_id or 0)
    if target_id <= 0: await message.answer("Вы не указали пользователя"); return
    try:
        users = await bot.api.users.get(user_ids=[str(target_id)])
        if users: await message.answer(f"Оригинальная ссылка [id{users[0].id}|пользователя]:\nhttps://vk.com/id{users[0].id}")
        else: await message.answer("Пользователь не найден.")
    except Exception: await message.answer("Не удалось найти пользователя.")

@bot.on.raw_event(GroupEventType.MESSAGE_EVENT, MessageEvent)
async def handle_message_event(event: MessageEvent):
    payload = event.get_payload_json() or {}
    if not isinstance(payload, dict) or payload.get("cmd") != "activate":
        await event.send_empty_answer(); return
    try:
        answer = await activate_chat(event.peer_id, event.user_id, event.group_id or GROUP_ID)
    except Exception as error:
        answer = f"Ошибка: ({type(error).__name__}: {error})"
    try: await event.send_empty_answer()
    except Exception: pass
    await event.send_message(answer)

@bot.on.message()
async def handle_all(message: Message):
    if message.action:
        if message.action.type in ("chat_invite_user", "chat_invite_user_by_link"):
            group_id = message.group_id or GROUP_ID
            member_id = message.action.member_id
            if member_id == -group_id: await handle_start(message)
            elif member_id > 0:
                if await db.is_banned(message.peer_id, member_id):
                    try:
                        users = await bot.api.users.get(user_ids=[member_id])
                        name = users[0].first_name if users else "Пользователь"
                        await bot.api.messages.remove_chat_user(chat_id=message.peer_id - PEER_OFFSET, member_id=member_id)
                        await message.answer(f"Пользователь [id{member_id}|{name}] находится в блокировке и был исключен.")
                    except Exception: pass
                    return
                try:
                    users = await bot.api.users.get(user_ids=[member_id])
                    if users:
                        mention = f"[id{member_id}|{users[0].first_name or 'Пользователь'}]"
                        await message.answer(f"{mention}, добро пожаловать в беседу!\nНе забудь прочитать закреплённое сообщение!\nПосмотреть ссылки на ресурсы отдела: «/info»")
                except Exception: pass
        return

    text = (message.text or "").strip()
    if not text: return
    parts = text.split()
    cmd = parts[0].lower()

    if cmd == "/start": await handle_start(message); return
    if cmd in ("/help", "помощь"): await handle_help(message); return
    if cmd in ("/type", "активировать"): await handle_type(message); return
    if cmd in ("/staff", "+staff"): await handle_staff(message); return
    if cmd in ("/addzam", "+addzam"): await handle_addzam(message); return
    if cmd in ("/delzam", "+delzam"): await handle_delzam(message); return
    if cmd in ("/addadmin", "+addadmin"): await handle_addadmin(message); return
    if cmd in ("/deladmin", "+deladmin"): await handle_deladmin(message); return
    if cmd in ("/delall", "+delall"): await handle_delall(message); return
    if cmd in ("/addmoder", "+addmoder"): await handle_addmoder(message); return
    if cmd in ("/delmoder", "+delmoder"): await handle_delmoder(message); return
    if cmd in ("/ban", "+ban"): await handle_ban(message); return
    if cmd in ("/unban", "+unban"): await handle_unban(message); return
    if cmd in ("/getban", "+getban"): await handle_getban(message); return
    if cmd in ("/vig", "+vig"): await handle_vig(message); return
    if cmd in ("/unvig", "+unvig"): await handle_unvig(message); return
    if cmd in ("/nvig", "+nvig"): await handle_nvig(message); return
    if cmd in ("/data", "+data"): await handle_data(message); return
    if cmd in ("/deldata", "+deldata"): await handle_deldata(message); return
    if cmd in ("/snick", "+snick"): await handle_snick(message); return
    if cmd in ("/rnick", "+rnick"): await handle_rnick(message); return
    if cmd in ("/nlist", "+nlist"): await handle_nlist(message); return
    if cmd in ("/kick", "+kick"): await handle_kick(message); return
    if cmd in ("/mute", "+mute"): await handle_mute(message); return
    if cmd in ("/unmute", "+unmute"): await handle_unmute(message); return
    if cmd in ("/stats", "+stats"): await handle_stats(message); return
    if cmd in ("/top", "+top"): await handle_top(message); return
    if cmd in ("/id", "+id"): await handle_id(message); return

    from_id = message.from_id or 0
    if message.peer_id >= PEER_OFFSET and from_id > 0:
        if await is_chat_added(message.peer_id):
            await db.increment_message(message.peer_id, from_id, await get_user_name(from_id))
