import aiosqlite

DB_PATH = "bot_data.db"

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS owner (
                user_id INTEGER PRIMARY KEY
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY,
                username TEXT
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone_number TEXT UNIQUE,
                session_string TEXT
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                action TEXT,
                target TEXT,
                account_phone TEXT
            )
        ''')
        await db.commit()

async def set_owner(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('DELETE FROM owner')
        await db.execute('INSERT INTO owner (user_id) VALUES (?)', (user_id,))
        await db.commit()

async def get_owner():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT user_id FROM owner') as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

async def is_authorized(user_id: int) -> bool:
    owner = await get_owner()
    if user_id == owner:
        return True
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT 1 FROM admins WHERE user_id = ?', (user_id,)) as cursor:
            return await cursor.fetchone() is not None

async def add_admin(user_id: int, username: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT OR IGNORE INTO admins (user_id, username) VALUES (?, ?)', (user_id, username))
        await db.commit()

async def remove_admin(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('DELETE FROM admins WHERE user_id = ?', (user_id,))
        await db.commit()

async def list_admins():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT user_id, username FROM admins') as cursor:
            return await cursor.fetchall()

async def add_account(phone: str, session_string: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT OR REPLACE INTO accounts (phone_number, session_string) VALUES (?, ?)', (phone, session_string))
        await db.commit()

async def get_all_accounts():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT id, phone_number, session_string FROM accounts') as cursor:
            return await cursor.fetchall()

async def delete_account(phone: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('DELETE FROM accounts WHERE phone_number = ?', (phone,))
        await db.commit()

async def log_activity(action: str, target: str, account_phone: str = "system"):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT INTO activity_log (action, target, account_phone) VALUES (?, ?, ?)',
                         (action, target, account_phone))
        await db.commit()

async def get_activity_log(limit=50):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT timestamp, action, target, account_phone FROM activity_log ORDER BY timestamp DESC LIMIT ?', (limit,)) as cursor:
            return await cursor.fetchall()
