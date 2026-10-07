import aiosqlite
from lutherbot.config import DATABASE_PATH

class Database:

    def __init__(self, conn: aiosqlite.Connection):
        self.conn = conn
        self.conn.row_factory = aiosqlite.Row

    
    # 1. Table Setup
    async def init_tables(self):
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS chores (
                cid INTEGER PRIMARY KEY,
                title TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS chore_assigments (
                chore_id INTEGER,
                user_id INTEGET NOT NULL,
                week TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                PRIMARY KEY 
                FOREIGN KEY (chore_id) REFERENCES chores (id) ON DELETE CASCADE,
                CONSTRAINT status_check CHECK (status IN ('pending', 'under_review', 'rejected', 'approved'))
            );
        """)
        await self.conn.commit()

    # 2. Quesy Methods (Used by Cogs)
    async def get_user_chores(self, guild_id: int, user_id: int):
        query = """
            SELECT
                ca.id AS assigmnet_id
        """
        async with self.conn.execute(
            "SELECT * FROM chores WHERE guild_id = ? AND assigned_to = ? AND status = 'pending'",
            (guild_id, user_id)
        ) as cursor:
            return await cursor.fetchall()
    
    async def update_chore_status(self, chore_id: int, status: str) -> bool:
        cursor = await self.conn.execute
