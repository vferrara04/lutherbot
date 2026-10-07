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
            CREATE TABLE IF NOT EXISTS chore_templates (
                cid INTEGER NOT NULL,
                uid INTEGER NOT NULL,
                PRIMARY KEY (cid, uid),
                FOREIGN KEY (cid) REFERENCES chores(cid) ON DELETE CASCADE,
                FOREIGN KEY (uid) REFERENCES users(uid) ON DELETE CASCADE
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
                CONSTRAINT status_check CHECK (status IN ('available', 'claimed', 'under_review', 'missed', 'rejected', 'completed'))
            );
            CREATE TABLE IF NOT EXISTS chore_assignments (
                cid INTEGER,
                uid INTEGER,
                week TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                thread_id INTEGER DEFAULT NULL,
                proof_mid id INTEGET DEFAULT NULL,
                PRIMARY KEY (cid, uid, week),
                FOREIGN KEY (cid) REFERENCES chores ON DELETE CASCADE,
                FOREIGN KEY (uid) REFERENCES users ON DELETE CASCADE,
                CONSTRAINT status_check CHECK (status IN ('pending', 'under_review', 'missed', 'rejected', 'approved'))
            );
            CREATE TABLE IF NOT EXISTS shopping_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_name TEXT NOT NULL,
                requested_by INTEGER NOT NULL,
                status TEXT DEFAULT 'needed' CHECK(status IN ('needed', 'purchased')),
            );
        """)
        await self.conn.commit()

    # 2. Roster and Chores
    
    async def upsert_user(self, user_id: int, first_name: str, last_name: str):
        await self.conn.execute("""
            INSERT INTO users (uid, first_name, last_name)
            VALUES (?, ?, ?)
            ON CONFLICT(uid) DO UPDATE SET
                first_name = excluded.first_name,
                last_name = excluded.last_name;
        """,
            (user_id, first_name, last_name)
        )
        await self.conn.commit()

    async def get_user(self, user_id: int) -> aiosqlite.Row | None:
        async with self.conn.execute(
            "SELECT * FROM users WHERE uid = ?", (user_id,)
        ) as cursor:
            return await cursor.fetchone()

    async def add_chore(self, title: str, description: str, hours: int, due_day: int | None = None) -> int:
        cursor = await self.conn.execute("""
            INSERT INTO
            chores (
                title,
                description,
                hours,
                due_day
            )
            VALUES (
                ?, ?, ?, ?
            )
        """,
            (title, description, hours, due_day)
        )
        await self.conn.commit()
        return cursor.lastrowid

    async def assign_chore(self, cid: int, uid: int, week: str):
        await self.conn.execute("""
            INSERT INTO chore_assignments (cid, uid, week)
            VALUES (?, ?, ?)
            ON CONFLICT(cid, uid, week) DO NOTHING;
            """,
                (cid, uid, week),
        )
        await self.conn.commit()

    async def add_chore_template(self, cid: int, uid: int):
        await self.conn.execute(
            """
            INSERT INTO chore_templates (cid, uid)
            VALUES (?, ?)
            ON CONFLICT(cid, uid) DO NOTHING;
            """,
            (cid, uid),
        )
        await self.conn.commit()
    
    async def generate_weekly_assignments(self, new_week: str) -> int:
        cursor = await self.conn.execute(
            """
            INSERT INTO chore_assignments (cid, uid, week, status)
            SELECT cid, uid, ?, 'pending'
            FROM chore_templates
            ON CONFLICT(cid, uid, week) DO NOTHING;
            """,
            (new_week,),
        )
        await self.conn.commit()
        return cursor.rowcount  # Returns how many assignments were created

    # 3. User queries and Submission
    async def get_user_chores(self, user_id: int, week: str):
        query = """
            SELECT
                c.cid AS chore_id,
                c.title,
                c.description,
                c.hours,
                ca.thread_id
            FROM chore_assigments ca, chores c
            WHERE ca.cid = c.cid
                AND ca.uid = ?
                AND ca.week = ?
                AND ca.status = IN ('pending', 'rejected');
        """
        async with self.conn.execute(
            query, (user_id, week)
        ) as cursor:
            return await cursor.fetchall()

    async def get_chore_partners(self, user_id: int, chore_id:int, week: str):
        query = """
            SELECT ca.uid, u.first_name, u.last_name
            FROM chore_assignments ca
            JOIN users u ON ca.uid = u.uid
            WHERE ca.cid = ?
              AND ca.week = ?
              AND ca.uid <> ?
              AND ca.status <> 'approved';
        """
        async with self.conn.execute(
            query, (chore_id, week, user_id)
        ) as cursor:
            return await cursor.fetchall()

    async def link_thread(self, chore_id: int, user_ids: list[int], week: str, thread_id: int):
        placeholders = ",".join("?" for _ in user_ids)
        query = f"""
            UPDATE chore_assignments
            SET thread_id = ?, status = 'under_review'
            WHERE cid = ? 
              AND week = ? 
              AND uid IN ({placeholders});
        """
        await self.conn.execute(query, (thread_id, chore_id, week, *user_ids))
        await self.conn.commit()

    async def submit_proof(self, chore_id: int, user_id:int, proof_mid: int) -> bool:
        await self.conn.execute("""
            UPDATE chore_assignments
            SET status = 'under_review',
            proof_mid = ?
            WHERE cid = ? AND uid = ?;
        """,
            (proof_mid, chore_id, user_id)
        )
        await self.conn.commit()
        
    # 4. Review Threads
    
    async def get_assignment_by_thread(self, thread_id: int):
        query = """
            SELECT ca.cid, ca.uid, ca.week, ca.status, c.title, c.hours
            FROM chore_assignments ca
            JOIN chores c ON ca.cid = c.cid
            WHERE ca.thread_id = ?;
        """
        async with self.conn.execute(query, (thread_id,)) as cursor:
            return await cursor.fetchall()

    async def update_status_by_thread(self, thread_id: int, status: str) -> int:
        cursor = await self.conn.execute(
            "UPDATE chore_assignments SET status = ? WHERE thread_id = ?",
            (status, thread_id),
        )
        await self.conn.commit()
        return cursor.rowcount
    
    async def get_missing_chores(self, week: str):
        query = """ 
            SELECT u.first_name, u.last_name, c.title, c.hours
            FROM chore_assignments ca, users u, chores c
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

    async def process_weekly_rollover(self, old_week: str, new_week: str):
        # 1. Add missed chore hours to users for any unfinished chores
        await self.conn.execute(
            """
            UPDATE users
            SET missed_chore_hours = missed_chore_hours + COALESCE((
                SELECT SUM(c.hours)
                FROM chore_assignments ca, chores c
                WHERE ca.uid = users.uid
                AND c.cid = ca.cid
                AND ca.week = ?
                AND ca.status IN ('pending', 'rejected')
            ), 0)
            WHERE uid IN (
                SELECT DISTINCT uid 
                FROM chore_assignments 
                WHERE week = ? AND status IN ('pending', 'rejected')
            );
            """,
            (old_week, old_week),
        )

        # 2. Flip old unfinished assignments to 'missed' (or archived)
        # Note: Ensure 'missed' is in your status_check constraint if you log it here
        await self.conn.execute(
            """
            UPDATE chore_assignments
            SET status = 'missed'
            WHERE week = ? AND status IN ('pending', 'rejected');
            """,
            (old_week,),
        )

        # 3. Provision the new week's chores from templates
        new_count = await self.generate_weekly_assignments(new_week)
        await self.conn.commit()
        return new_count
            
    # 5. Makeup Bounties

    async def add_makeup_chore(self, cid: int, week: str) -> int:
        cursor = await self.conn.execute(
            "INSERT INTO makeup_chores (cid, week) VALUES (?, ?)",
            (cid, week),
        )
        await self.conn.commit()
        return cursor.lastrowid
    
    async def get_available_makeups(self):
        """Returns all unclaimed tasks in the makeup pool."""
        query = """
            SELECT m.mid, c.title, c.hours, m.week
            FROM makeup_chores m
            JOIN chores c ON m.cid = c.cid
            WHERE m.status = 'available'
            ORDER BY m.mid ASC;
        """
        async with self.conn.execute(query) as cursor:
            return await cursor.fetchall()
    
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
    
    async def resolve_missed_chores(self, makeup_id: int, user_id: int):
        await self.conn.execute(
            """
            UPDATE makeup_chores
            SET status = 'completed'
            WHERE id = ? AND uid = ?;
            """,
            (makeup_id, user_id),
        )

        await self.conn.execute(
            """
            UPDATE users
            SET missed_chore_hours = MAX(0, missed_chore_hours - (
                SELECT c.hours 
                FROM makeup_chores m 
                JOIN chores c ON m.cid = c.cid 
                WHERE m.id = ?
            ))
            WHERE uid = ?;
            """,
            (makeup_id, user_id),
        )
        await self.conn.commit()

    # Shopping list:
    async def add_shopping_item(
        self, guild_id: int, item_name: str, requested_by: int
    ) -> int:
        cursor = await self.conn.execute(
            """
            INSERT INTO shopping_items (item_name, requested_by)
            VALUES (?, ?, ?)
            """,
            (item_name, requested_by),
        )
        await self.conn.commit()
        return cursor.lastrowid


    async def get_active_shopping_items(self) -> list[aiosqlite.Row]:
        async with self.conn.execute(
            """
            SELECT s.*, u.first_name AS requester_name, c.first_name AS claimer_name
            FROM shopping_items s
            LEFT JOIN users u ON s.requested_by = u.uid
            LEFT JOIN users c ON s.claimed_by = c.uid
            WHERE s.status IN ('needed', 'claimed')
            ORDER BY s.status DESC, s.id ASC
            """,
            (guild_id,),
        ) as cursor:
            return await cursor.fetchall()


    async def claim_shopping_item(
        self, item_id: int, user_id: int, guild_id: int
    ) -> bool:
        cursor = await self.conn.execute(
            """
            UPDATE shopping_items
            SET claimed_by = ?, status = 'claimed'
            WHERE id = ? AND guild_id = ? AND status = 'needed'
            """,
            (user_id, item_id, guild_id),
        )
        await self.conn.commit()
        return cursor.rowcount > 0


    async def complete_shopping_item(
        self, item_id: int, user_id: int, guild_id: int, cost: float
    ) -> bool:
        cursor = await self.conn.execute(
            """
            UPDATE shopping_items
            SET status = 'purchased', cost = ?
            WHERE id = ? AND guild_id = ? AND (claimed_by = ? OR claimed_by IS NULL)
            """,
            (cost, item_id, guild_id, user_id),
        )
        await self.conn.commit()
        return cursor.rowcount > 0