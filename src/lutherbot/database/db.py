import aiosqlite
from lutherbot.config import DATABASE_PATH

class Database:

    def __init__(self, conn: aiosqlite.Connection):
        self.conn = conn
        self.conn.row_factory = aiosqlite.Row

    
    # 1. Table Setup
    async def init_tables(self):
        await self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS users(
                uid INTEGER PRIMARY KEY,
                first_name TEXT NOT NULL,
                last_name TEXT NOT NULL,
                missed_chore_hours INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS chores (
                cid INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT,
                hours INTEGER NOT NULL,
                due_day INTEGER DEFAULT NULL
            );
            CREATE TABLE IF NOT EXISTS makeup_chores (
                mid INTEGER PRIMARY KEY,
                cid INTEGER,
                uid INTEGER,
                status TEXT DEFAULT 'available',
                thread_id INTEGER DEFAULT NULL,
                week TEXT NOT NULL,
                FOREIGN KEY (cid) REFERENCES chores ON DELETE CASCADE,
                FOREIGN KEY (uid) REFERENCES users ON DELETE CASCADE,
                CONSTRAINT status_check CHECK (status IN ('available', 'claimed', 'under_review', 'rejected', 'completed'))
            );
            CREATE TABLE IF NOT EXISTS chore_assignments (
                cid INTEGER,
                uid INTEGER,
                week TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                thread_id INTEGER DEFAULT NULL,
                PRIMARY KEY (cid, uid),
                FOREIGN KEY (cid) REFERENCES chores ON DELETE CASCADE,
                FOREIGN KEY (uid) REFERENCES users ON DELETE CASCADE,
                CONSTRAINT status_check CHECK (status IN ('pending', 'under_review', 'rejected', 'approved'))
            );
        """)
        await self.conn.commit()

    # 2. Roster and Chores
    
    # add data
    
    # 3. User queries and Submission
    async def get_user_chores(self, user_id: int, week: str):
        query = """
            SELECT
                c.cid AS chore_id,
                c.title,
                c.description
            FROM chore_assigments ca, chores c
            WHERE ca.cid = c.cid
                AND ca.uid = ?
                AND ca.week = ?
                AND ca.status = 'pending';
        """
        async with self.conn.execute(
            query, (user_id, week)
        ) as cursor:
            return await cursor.fetchall()
    
    async def submit_proof(self, chore_id: int, user_id:int, proof_url: str) -> bool:
        await self.conn.execute("""
            UPDATE chore_assignments
            SET status = 'under_review',
            proof_url = ?,
            WHERE cid = ? AND uid = ?;
        """,
            (proof_url, chore_id, user_id)
        )
        await self.conn.commit()
        
    # link threads to CA
    
    # Chore partners
        
    # Review Threads
    
    # update status of thread
    
     async def get_missing_chores(self, week: str):
        query = """ 
            SELECT u.first_name, u.last_name, c.title, c.hours
            FROM chore_assigments ca, users u, chores c
            WHERE ca.status IN ('pending', 'rejected')
                AND u.uid = ca.uid
                AND c.cid = ca.cid
                AND ca.week = ?
            ORDER BY u.first_name, u.last_name;
        
        """
        async with self.conn.execute(
            query, (week,)
        ) as cursor:
            return await cursor.fetchall()
            
    # Makeup Bounties
    
    # getall makeups
    
     async def claim_makeup(self, chore_id: int, user_id: int) -> bool:
        cursor = await self.conn.execute("""
            UPDATE makeup_chores
            SET uid = ?, status = 'claimed'
            WHERE cid = ? 
                AND status = 'available'
        """,
            (user_id, chore_id)
            )
        await self.conn.commit()
        return cursor.rowcount > 0
    
     async def resolve_missed_chores(self, chore_id: int, user_id: int):
        await self.conn.executescript("""
            UPDATE makeup_chores
            SET status = 'completed'
                WHERE uid = ? 
                AND cid = ?;
            UPDATE users
            SET missed_chore_hours = MAX(0, missed_chore_hours - c.hours)
            FROM chores c
                WHERE uid = ? 
                AND c.cid = ?;
            
        """,
            (user_id, chore_id, user_id, chore_id)
            )
        await self.conn.commit()
