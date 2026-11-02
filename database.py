import os
import time
import aiosqlite
from config import DB_PATH

def _ensure_dir(path: str) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)

async def _connect() -> aiosqlite.Connection:
    _ensure_dir(DB_PATH)
    db = await aiosqlite.connect(DB_PATH, timeout=10)
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA busy_timeout=10000")
    return db

async def init_db():
    db = await _connect()
    try:
        await db.execute("CREATE TABLE IF NOT EXISTS chats (id INTEGER PRIMARY KEY, title TEXT, added_at TEXT DEFAULT CURRENT_TIMESTAMP)")
        await db.execute("CREATE TABLE IF NOT EXISTS user_stats (chat_id INTEGER, user_id INTEGER, nick_name TEXT, message_count INTEGER DEFAULT 0, PRIMARY KEY (chat_id, user_id))")
        await db.execute("CREATE TABLE IF NOT EXISTS user_roles (chat_id INTEGER, user_id INTEGER, role INTEGER DEFAULT 0, appointed_at TEXT, PRIMARY KEY (chat_id, user_id))")
        await db.execute("CREATE TABLE IF NOT EXISTS user_nicks (chat_id INTEGER, user_id INTEGER, nick_name TEXT, PRIMARY KEY (chat_id, user_id))")
        await db.execute("CREATE TABLE IF NOT EXISTS chat_bans (chat_id INTEGER, user_id INTEGER, PRIMARY KEY (chat_id, user_id))")
        await db.execute("CREATE TABLE IF NOT EXISTS user_vigs (chat_id INTEGER, user_id INTEGER, vig_count INTEGER DEFAULT 0, PRIMARY KEY (chat_id, user_id))")
        
        try: await db.execute("ALTER TABLE chat_bans ADD COLUMN reason TEXT DEFAULT 'Не указана'")
        except Exception: pass
        try: await db.execute("ALTER TABLE chat_bans ADD COLUMN banned_by INTEGER DEFAULT 0")
        except Exception: pass
        try: await db.execute("ALTER TABLE chat_bans ADD COLUMN ban_until INTEGER DEFAULT 0")
        except Exception: pass
        try: await db.execute("ALTER TABLE user_roles ADD COLUMN appointed_at TEXT")
        except Exception: pass

        await db.commit()
    finally: await db.close()

async def add_chat(chat_id: int, title: str):
    db = await _connect()
    try:
        await db.execute("INSERT OR IGNORE INTO chats (id, title) VALUES (?, ?)", (chat_id, title))
        await db.commit()
    finally: await db.close()

async def get_added_chats() -> set[int]:
    db = await _connect()
    try:
        async with db.execute("SELECT id FROM chats") as cur:
            rows = await cur.fetchall()
        return {row[0] for row in rows}
    finally: await db.close()

async def is_chat_added(chat_id: int) -> bool:
    db = await _connect()
    try:
        async with db.execute("SELECT 1 FROM chats WHERE id = ?", (chat_id,)) as cur:
            return await cur.fetchone() is not None
    finally: await db.close()

async def increment_message(chat_id: int, user_id: int, nick_name: str):
    db = await _connect()
    try:
        await db.execute("""
            INSERT INTO user_stats (chat_id, user_id, nick_name, message_count)
            VALUES (?, ?, ?, 1)
            ON CONFLICT(chat_id, user_id) DO UPDATE SET
                message_count = message_count + 1,
                nick_name = excluded.nick_name
        """, (chat_id, user_id, nick_name))
        await db.commit()
    finally: await db.close()

async def get_stats(chat_id: int):
    db = await _connect()
    try:
        async with db.execute("SELECT user_id, nick_name, message_count FROM user_stats WHERE chat_id = ?", (chat_id,)) as cur:
            return await cur.fetchall()
    finally: await db.close()

async def get_top_stats(chat_id: int, limit: int = 10):
    db = await _connect()
    try:
        async with db.execute("SELECT user_id, nick_name, message_count FROM user_stats WHERE chat_id = ? ORDER BY message_count DESC LIMIT ?", (chat_id, limit)) as cur:
            return await cur.fetchall()
    finally: await db.close()

async def get_user_role(chat_id: int, user_id: int) -> int:
    db = await _connect()
    try:
        async with db.execute("SELECT role FROM user_roles WHERE chat_id = ? AND user_id = ?", (chat_id, user_id)) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0
    finally: await db.close()

async def set_user_role(chat_id: int, user_id: int, role: int):
    db = await _connect()
    try:
        if role == 0:
            await db.execute("DELETE FROM user_roles WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
        else:
            today = time.strftime("%Y-%m-%d")
            await db.execute("""
                INSERT INTO user_roles (chat_id, user_id, role, appointed_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(chat_id, user_id) DO UPDATE SET 
                    role = excluded.role,
                    appointed_at = excluded.appointed_at
            """, (chat_id, user_id, role, today))
        await db.commit()
    finally: await db.close()

async def set_user_date(chat_id: int, user_id: int, date_str: str):
    db = await _connect()
    try:
        await db.execute("UPDATE user_roles SET appointed_at = ? WHERE chat_id = ? AND user_id = ?", (date_str, chat_id, user_id))
        await db.commit()
    finally: await db.close()

async def remove_user_date(chat_id: int, user_id: int):
    db = await _connect()
    try:
        await db.execute("UPDATE user_roles SET appointed_at = NULL WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
        await db.commit()
    finally: await db.close()

async def get_user_date(chat_id: int, user_id: int) -> str | None:
    db = await _connect()
    try:
        async with db.execute("SELECT appointed_at FROM user_roles WHERE chat_id = ? AND user_id = ?", (chat_id, user_id)) as cur:
            row = await cur.fetchone()
            return row[0] if row else None
    finally: await db.close()

async def set_nick(chat_id: int, user_id: int, nick_name: str):
    db = await _connect()
    try:
        await db.execute("""
            INSERT INTO user_nicks (chat_id, user_id, nick_name)
            VALUES (?, ?, ?)
            ON CONFLICT(chat_id, user_id) DO UPDATE SET nick_name = excluded.nick_name
        """, (chat_id, user_id, nick_name))
        await db.commit()
    finally: await db.close()

async def remove_nick(chat_id: int, user_id: int):
    db = await _connect()
    try:
        await db.execute("DELETE FROM user_nicks WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
        await db.commit()
    finally: await db.close()

async def get_nick(chat_id: int, user_id: int) -> str | None:
    db = await _connect()
    try:
        async with db.execute("SELECT nick_name FROM user_nicks WHERE chat_id = ? AND user_id = ?", (chat_id, user_id)) as cur:
            row = await cur.fetchone()
            return row[0] if row else None
    finally: await db.close()

async def get_all_nicks(chat_id: int) -> list[tuple[int, str]]:
    db = await _connect()
    try:
        async with db.execute("SELECT user_id, nick_name FROM user_nicks WHERE chat_id = ?", (chat_id,)) as cur:
            return await cur.fetchall()
    finally: await db.close()

async def get_all_moderators(chat_id: int) -> list[int]:
    db = await _connect()
    try:
        async with db.execute("SELECT user_id FROM user_roles WHERE chat_id = ? AND role = 1", (chat_id,)) as cur:
            rows = await cur.fetchall()
            return [row[0] for row in rows]
    finally: await db.close()

async def get_all_deputies(chat_id: int) -> list[int]:
    db = await _connect()
    try:
        async with db.execute("SELECT user_id FROM user_roles WHERE chat_id = ? AND role = 2", (chat_id,)) as cur:
            rows = await cur.fetchall()
            return [row[0] for row in rows]
    finally: await db.close()

async def add_ban(chat_id: int, user_id: int, reason: str = "Не указана", banned_by: int = 0, days: int = 0):
    ban_until = int(time.time()) + (days * 86400) if days > 0 else 0
    db = await _connect()
    try:
        await db.execute("""
            INSERT INTO chat_bans (chat_id, user_id, reason, banned_by, ban_until)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(chat_id, user_id) DO UPDATE SET
                reason = excluded.reason,
                banned_by = excluded.banned_by,
                ban_until = excluded.ban_until
        """, (chat_id, user_id, reason, banned_by, ban_until))
        await db.commit()
    finally: await db.close()

async def remove_ban(chat_id: int, user_id: int):
    db = await _connect()
    try:
        await db.execute("DELETE FROM chat_bans WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
        await db.commit()
    finally: await db.close()

async def is_banned(chat_id: int, user_id: int) -> bool:
    db = await _connect()
    try:
        async with db.execute("SELECT ban_until FROM chat_bans WHERE chat_id = ? AND user_id = ?", (chat_id, user_id)) as cur:
            row = await cur.fetchone()
            if row:
                ban_until = row[0]
                if ban_until > 0 and ban_until < time.time():
                    await db.execute("DELETE FROM chat_bans WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
                    await db.commit()
                    return False
                return True
            return False
    finally: await db.close()

async def get_ban_info(chat_id: int, user_id: int) -> tuple[str, int, int] | None:
    db = await _connect()
    try:
        async with db.execute("SELECT reason, banned_by, ban_until FROM chat_bans WHERE chat_id = ? AND user_id = ?", (chat_id, user_id)) as cur:
            row = await cur.fetchone()
            if row:
                ban_until = row[2]
                if ban_until > 0 and ban_until < time.time():
                    await db.execute("DELETE FROM chat_bans WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
                    await db.commit()
                    return None
                return row
            return None
    finally: await db.close()

async def get_all_bans(chat_id: int) -> list[tuple[int, str, int, int]]:
    db = await _connect()
    try:
        async with db.execute("SELECT user_id, reason, banned_by, ban_until FROM chat_bans WHERE chat_id = ?", (chat_id,)) as cur:
            return await cur.fetchall()
    finally: await db.close()

async def add_vig(chat_id: int, user_id: int, amount: int):
    db = await _connect()
    try:
        await db.execute("""
            INSERT INTO user_vigs (chat_id, user_id, vig_count)
            VALUES (?, ?, MIN(?, 3))
            ON CONFLICT(chat_id, user_id) DO UPDATE SET vig_count = MIN(vig_count + excluded.vig_count, 3)
        """, (chat_id, user_id, amount))
        await db.commit()
    finally: await db.close()

async def remove_vig(chat_id: int, user_id: int, amount: int):
    db = await _connect()
    try:
        await db.execute("""
            UPDATE user_vigs SET vig_count = MAX(0, vig_count - ?) WHERE chat_id = ? AND user_id = ?
        """, (amount, chat_id, user_id))
        await db.commit()
    finally: await db.close()

async def get_vig(chat_id: int, user_id: int) -> int:
    db = await _connect()
    try:
        async with db.execute("SELECT vig_count FROM user_vigs WHERE chat_id = ? AND user_id = ?", (chat_id, user_id)) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0
    finally: await db.close()

async def get_all_vigs(chat_id: int) -> list[tuple[int, int]]:
    db = await _connect()
    try:
        async with db.execute("SELECT user_id, vig_count FROM user_vigs WHERE chat_id = ? AND vig_count > 0", (chat_id,)) as cur:
            return await cur.fetchall()
    finally: await db.close()

async def remove_all_roles(chat_id: int):
    db = await _connect()
    try:
        await db.execute("DELETE FROM user_roles WHERE chat_id = ?", (chat_id,))
        await db.commit()
    finally: await db.close()
