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
                FOREIGN KEY (cid) REFERENCES chores(cid) ON DELETE CASCADE,
                FOREIGN KEY (uid) REFERENCES users(uid) ON DELETE CASCADE,
                CONSTRAINT status_check CHECK (status IN ('available', 'claimed', 'under_review', 'missed', 'rejected', 'approved'))
            );
            CREATE TABLE IF NOT EXISTS chore_assignments (
                cid INTEGER,
                uid INTEGER,
                week TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                thread_id INTEGER DEFAULT NULL,
                proof_mid INTEGER DEFAULT NULL,
                PRIMARY KEY (cid, uid, week),
                FOREIGN KEY (cid) REFERENCES chores(cid) ON DELETE CASCADE,
                FOREIGN KEY (uid) REFERENCES users(uid) ON DELETE CASCADE,
                CONSTRAINT status_check CHECK (status IN ('pending', 'under_review', 'missed', 'rejected', 'approved'))
            );
            CREATE TABLE IF NOT EXISTS shopping_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER DEFAULT 0,
                item_name TEXT NOT NULL,
                quantity TEXT DEFAULT '1',
                requested_by INTEGER NOT NULL,
                claimed_by INTEGER DEFAULT NULL,
                cost REAL DEFAULT NULL,
                status TEXT DEFAULT 'needed' CHECK(status IN ('needed', 'claimed', 'purchased'))
            );
        """)
        await self.conn.commit()

    # 2. Roster and Chores
    async def upsert_user(self, user_id: int, first_name: str, last_name: str, missed_chore_hours: int = 0):
        await self.conn.execute("""
            INSERT INTO users (uid, first_name, last_name, missed_chore_hours)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(uid) DO UPDATE SET
                first_name = excluded.first_name,
                last_name = excluded.last_name;
        """,
            (user_id, first_name, last_name, missed_chore_hours)
        )
        await self.conn.commit()

    async def get_user(self, user_id: int) -> aiosqlite.Row | None:
        async with self.conn.execute(
            "SELECT * FROM users WHERE uid = ?", (user_id,)
        ) as cursor:
            return await cursor.fetchone()

    async def get_all_users(self) -> list[aiosqlite.Row]:
        async with self.conn.execute(
            "SELECT * FROM users ORDER BY first_name, last_name"
        ) as cursor:
            return await cursor.fetchall()

    async def add_chore(self, title: str, description: str, hours: int, due_day: int | None = None) -> int:
        cursor = await self.conn.execute("""
            INSERT INTO chores (title, description, hours, due_day)
            VALUES (?, ?, ?, ?)
        """,
            (title, description, hours, due_day)
        )
        await self.conn.commit()
        return cursor.lastrowid

    async def get_chore(self, chore_id: int) -> aiosqlite.Row | None:
        async with self.conn.execute(
            "SELECT * FROM chores WHERE cid = ?", (chore_id,)
        ) as cursor:
            return await cursor.fetchone()

    async def get_all_chores(self) -> list[aiosqlite.Row]:
        async with self.conn.execute(
            "SELECT * FROM chores ORDER BY cid ASC"
        ) as cursor:
            return await cursor.fetchall()

    async def edit_chore(
        self, cid: int, title: str, description: str, hours: int, due_day: int | None = None
    ) -> bool:
        cursor = await self.conn.execute(
            """
            UPDATE chores
            SET title = ?, description = ?, hours = ?, due_day = ?
            WHERE cid = ?
            """,
            (title, description, hours, due_day, cid),
        )
        await self.conn.commit()
        return cursor.rowcount > 0

    async def delete_chore(self, cid: int) -> bool:
        cursor = await self.conn.execute(
            "DELETE FROM chores WHERE cid = ?", (cid,)
        )
        await self.conn.commit()
        return cursor.rowcount > 0

    async def assign_chore(self, cid: int, uid: int, week: str):
        await self.conn.execute(
            """
            INSERT OR IGNORE INTO chore_assignments (cid, uid, week)
            VALUES (?, ?, ?);
            """,
            (cid, uid, week),
        )
        await self.conn.commit()

    async def get_weekly_assignments_detailed(self, week: str) -> list[aiosqlite.Row]:
        query = """
            SELECT ca.cid, ca.uid, ca.week, ca.status, ca.thread_id,
                   u.first_name, u.last_name, c.title, c.hours, c.due_day
            FROM chore_assignments ca
            JOIN users u ON ca.uid = u.uid
            JOIN chores c ON ca.cid = c.cid
            WHERE ca.week = ?
            ORDER BY u.first_name, c.title;
        """
        async with self.conn.execute(query, (week,)) as cursor:
            return await cursor.fetchall()

    async def update_assignment_status(
        self, cid: int, uid: int, week: str, status: str
    ) -> bool:
        cursor = await self.conn.execute(
            """
            UPDATE chore_assignments
            SET status = ?
            WHERE cid = ? AND uid = ? AND week = ?;
            """,
            (status, cid, uid, week),
        )
        await self.conn.commit()
        return cursor.rowcount > 0

    async def reassign_chore(
        self, old_uid: int, new_uid: int, cid: int, week: str
    ) -> bool:
        cursor = await self.conn.execute(
            """
            UPDATE chore_assignments
            SET uid = ?
            WHERE cid = ? AND uid = ? AND week = ?;
            """,
            (new_uid, cid, old_uid, week),
        )
        await self.conn.commit()
        return cursor.rowcount > 0

    async def delete_assignment(self, cid: int, uid: int, week: str) -> bool:
        cursor = await self.conn.execute(
            """
            DELETE FROM chore_assignments
            WHERE cid = ? AND uid = ? AND week = ?;
            """,
            (cid, uid, week),
        )
        await self.conn.commit()
        return cursor.rowcount > 0

    async def add_chore_template(self, cid: int, uid: int):
        await self.conn.execute(
            """
            INSERT OR IGNORE INTO chore_templates (cid, uid)
            VALUES (?, ?);
            """,
            (cid, uid),
        )
        await self.conn.commit()
    
    async def generate_weekly_assignments(
        self, new_week: str, fallback_from_week: str | None = None
    ) -> int:
        cursor = await self.conn.execute(
            """
            INSERT OR IGNORE INTO chore_assignments (cid, uid, week, status)
            SELECT cid, uid, ?, 'pending'
            FROM chore_templates;
            """,
            (new_week,),
        )
        count = cursor.rowcount

        # If no templates were configured, roll over assignments from the previous week as a fallback
        if count == 0 and fallback_from_week:
            cursor2 = await self.conn.execute(
                """
                INSERT OR IGNORE INTO chore_assignments (cid, uid, week, status)
                SELECT DISTINCT cid, uid, ?, 'pending'
                FROM chore_assignments
                WHERE week = ?;
                """,
                (new_week, fallback_from_week),
            )
            count = cursor2.rowcount

        await self.conn.commit()
        return count

    # 3. User queries and Submission
    async def get_user_chores(self, user_id: int, week: str):
        query = """
            SELECT
                c.cid AS chore_id,
                c.title,
                c.description,
                c.hours,
                ca.status,
                ca.thread_id
            FROM chore_assignments ca
            JOIN chores c ON ca.cid = c.cid
            WHERE ca.uid = ?
                AND ca.week = ?
                AND ca.status IN ('pending', 'rejected');
        """
        async with self.conn.execute(query, (user_id, week)) as cursor:
            return await cursor.fetchall()

    async def get_chore_partners(self, user_id: int, chore_id: int, week: str):
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

    async def link_makeup_thread(self, mid: int, thread_id: int):
        query = """
            UPDATE makeup_chores
            SET thread_id = ?, status = 'under_review'
            WHERE mid = ?;
        """
        await self.conn.execute(query, (thread_id, mid))
        await self.conn.commit()

    async def submit_proof(self, chore_id: int, user_id: int, proof_mid: int) -> bool:
        await self.conn.execute("""
            UPDATE chore_assignments
            SET status = 'under_review',
            proof_mid = ?
            WHERE cid = ? AND uid = ?;
        """,
            (proof_mid, chore_id, user_id)
        )
        await self.conn.commit()
        return True

    # 4. Review Threads
    async def get_assignment_by_thread(self, thread_id: int):
        # Check chore assignments first
        query = """
            SELECT ca.cid, ca.uid, ca.week, ca.status, c.title, c.hours, 'regular' as chore_type, NULL as mid
            FROM chore_assignments ca
            JOIN chores c ON ca.cid = c.cid
            WHERE ca.thread_id = ?;
        """
        async with self.conn.execute(query, (thread_id,)) as cursor:
            rows = await cursor.fetchall()
            if rows:
                return rows

        # Check makeup chores if not found in regular assignments
        makeup_query = """
            SELECT m.cid, m.uid, m.week, m.status, c.title, c.hours, 'makeup' as chore_type, m.mid
            FROM makeup_chores m
            JOIN chores c ON m.cid = c.cid
            WHERE m.thread_id = ?;
        """
        async with self.conn.execute(makeup_query, (thread_id,)) as cursor:
            return await cursor.fetchall()

    async def update_status_by_thread(self, thread_id: int, status: str) -> int:
        c1 = await self.conn.execute(
            "UPDATE chore_assignments SET status = ? WHERE thread_id = ?",
            (status, thread_id),
        )
        c2 = await self.conn.execute(
            "UPDATE makeup_chores SET status = ? WHERE thread_id = ?",
            (status, thread_id),
        )
        await self.conn.commit()
        return c1.rowcount + c2.rowcount
    
    async def get_missing_chores(self, week: str):
        query = """ 
            SELECT u.first_name, u.last_name, c.title, c.hours
            FROM chore_assignments ca
            JOIN users u ON u.uid = ca.uid
            JOIN chores c ON c.cid = ca.cid
            WHERE ca.status IN ('pending', 'rejected')
                AND ca.week = ?
            ORDER BY u.first_name, u.last_name;
        """
        async with self.conn.execute(query, (week,)) as cursor:
            return await cursor.fetchall()

    async def process_weekly_rollover(self, old_week: str, new_week: str):
        # 1. Add missed chore hours to users for any unfinished chores
        await self.conn.execute(
            """
            UPDATE users
            SET missed_chore_hours = missed_chore_hours + COALESCE((
                SELECT SUM(c.hours)
                FROM chore_assignments ca
                JOIN chores c ON c.cid = ca.cid
                WHERE ca.uid = users.uid
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

        # 2. Flip old unfinished assignments to 'missed'
        await self.conn.execute(
            """
            UPDATE chore_assignments
            SET status = 'missed'
            WHERE week = ? AND status IN ('pending', 'rejected');
            """,
            (old_week,),
        )

        # 3. Provision the new week's chores from templates (or fallback to previous week)
        new_count = await self.generate_weekly_assignments(new_week, fallback_from_week=old_week)
        await self.conn.commit()
        return new_count

    async def get_pending_threads(self) -> list[aiosqlite.Row]:
        """Returns all chore assignments and makeup bounties currently awaiting review with an open thread."""
        query = """
            SELECT ca.cid, ca.uid, ca.week, ca.status, ca.thread_id,
                   u.first_name, u.last_name, c.title, c.hours, 'regular' as chore_type, NULL as mid
            FROM chore_assignments ca
            JOIN users u ON ca.uid = u.uid
            JOIN chores c ON ca.cid = c.cid
            WHERE ca.thread_id IS NOT NULL AND ca.status IN ('under_review', 'pending')
            UNION ALL
            SELECT m.cid, m.uid, m.week, m.status, m.thread_id,
                   COALESCE(u.first_name, 'Unassigned') as first_name,
                   COALESCE(u.last_name, '') as last_name,
                   c.title, c.hours, 'makeup' as chore_type, m.mid
            FROM makeup_chores m
            JOIN chores c ON m.cid = c.cid
            LEFT JOIN users u ON m.uid = u.uid
            WHERE m.thread_id IS NOT NULL AND m.status IN ('under_review', 'claimed')
            ORDER BY week DESC, first_name ASC;
        """
        async with self.conn.execute(query) as cursor:
            return await cursor.fetchall()

    async def set_user_missed_hours(self, user_id: int, hours: int) -> bool:
        """Sets the exact missed chore hours debt for a user."""
        cursor = await self.conn.execute(
            """
            UPDATE users
            SET missed_chore_hours = ?
            WHERE uid = ?;
            """,
            (max(0, hours), user_id),
        )
        await self.conn.commit()
        return cursor.rowcount > 0

    async def adjust_user_missed_hours(self, user_id: int, delta: int) -> int | None:
        """Adjusts a user's missed hours debt by +/- delta, returning new total."""
        user = await self.get_user(user_id)
        if not user:
            return None
        new_debt = max(0, user["missed_chore_hours"] + delta)
        await self.set_user_missed_hours(user_id, new_debt)
        return new_debt
            
    # 5. Makeup Bounties
    async def add_makeup_chore(self, cid: int, week: str) -> int:
        cursor = await self.conn.execute(
            "INSERT INTO makeup_chores (cid, week) VALUES (?, ?)",
            (cid, week),
        )
        await self.conn.commit()
        return cursor.lastrowid
    
    async def get_available_makeups(self):
        query = """
            SELECT m.mid, c.title, c.hours, m.week
            FROM makeup_chores m
            JOIN chores c ON m.cid = c.cid
            WHERE m.status = 'available'
            ORDER BY m.mid ASC;
        """
        async with self.conn.execute(query) as cursor:
            return await cursor.fetchall()
    
    async def claim_makeup(self, makeup_id: int, user_id: int) -> bool:
        cursor = await self.conn.execute("""
            UPDATE makeup_chores
            SET uid = ?, status = 'claimed'
            WHERE mid = ? 
                AND status = 'available';
        """,
            (user_id, makeup_id)
        )
        await self.conn.commit()
        return cursor.rowcount > 0
    
    async def resolve_missed_chores(self, makeup_id: int, user_id: int):
        await self.conn.execute(
            """
            UPDATE makeup_chores
            SET status = 'approved'
            WHERE mid = ? AND uid = ?;
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
                WHERE m.mid = ?
            ))
            WHERE uid = ?;
            """,
            (makeup_id, user_id),
        )
        await self.conn.commit()

    async def delete_makeup_chore(self, makeup_id: int) -> bool:
        cursor = await self.conn.execute(
            "DELETE FROM makeup_chores WHERE mid = ? AND status = 'available'",
            (makeup_id,),
        )
        await self.conn.commit()
        return cursor.rowcount > 0

    async def get_makeups_by_week(self, week: str) -> list[aiosqlite.Row]:
        query = """
            SELECT m.mid, m.cid, m.week, m.status, m.uid, m.thread_id,
                   c.title, c.hours, c.due_day,
                   u.first_name, u.last_name
            FROM makeup_chores m
            JOIN chores c ON m.cid = c.cid
            LEFT JOIN users u ON m.uid = u.uid
            WHERE m.week = ?
            ORDER BY m.mid ASC;
        """
        async with self.conn.execute(query, (week,)) as cursor:
            return await cursor.fetchall()

    async def get_user_claimed_makeups(self, user_id: int) -> list[aiosqlite.Row]:
        query = """
            SELECT m.mid, m.cid, m.week, m.status, m.thread_id,
                   c.title, c.hours
            FROM makeup_chores m
            JOIN chores c ON m.cid = c.cid
            WHERE m.uid = ? AND m.status IN ('claimed', 'under_review')
            ORDER BY m.mid ASC;
        """
        async with self.conn.execute(query, (user_id,)) as cursor:
            return await cursor.fetchall()

    # 6. Shopping list
    async def add_shopping_item(
        self, guild_id: int, item_name: str, requested_by: int, quantity: str = "1"
    ) -> int:
        cursor = await self.conn.execute(
            """
            INSERT INTO shopping_items (guild_id, item_name, quantity, requested_by)
            VALUES (?, ?, ?, ?)
            """,
            (guild_id, item_name, quantity, requested_by),
        )
        await self.conn.commit()
        return cursor.lastrowid

    async def get_active_shopping_items(self, guild_id: int = 0) -> list[aiosqlite.Row]:
        query = """
            SELECT s.*, u.first_name AS requester_name, c.first_name AS claimer_name
            FROM shopping_items s
            LEFT JOIN users u ON s.requested_by = u.uid
            LEFT JOIN users c ON s.claimed_by = c.uid
            WHERE s.status IN ('needed', 'claimed')
            ORDER BY s.status DESC, s.id ASC;
        """
        async with self.conn.execute(query) as cursor:
            return await cursor.fetchall()

    async def fetch_and_reset_shopping_list(self, guild_id: int = 0) -> list[aiosqlite.Row]:
        query = """
            SELECT s.*, u.first_name, u.last_name
            FROM shopping_items s
            LEFT JOIN users u ON s.requested_by = u.uid
            WHERE s.status = 'needed'
            ORDER BY s.id ASC;
        """
        async with self.conn.execute(query) as cursor:
            items = await cursor.fetchall()

        await self.conn.execute(
            "UPDATE shopping_items SET status = 'purchased' WHERE status = 'needed';"
        )
        await self.conn.commit()
        return items

    async def claim_shopping_item(
        self, item_id: int, user_id: int, guild_id: int = 0
    ) -> bool:
        cursor = await self.conn.execute(
            """
            UPDATE shopping_items
            SET claimed_by = ?, status = 'claimed'
            WHERE id = ? AND status = 'needed'
            """,
            (user_id, item_id),
        )
        await self.conn.commit()
        return cursor.rowcount > 0

    async def complete_shopping_item(
        self, item_id: int, user_id: int, guild_id: int = 0, cost: float | None = None
    ) -> bool:
        cursor = await self.conn.execute(
            """
            UPDATE shopping_items
            SET status = 'purchased', cost = ?
            WHERE id = ? AND (claimed_by = ? OR claimed_by IS NULL)
            """,
            (cost, item_id, user_id),
        )
        await self.conn.commit()
        return cursor.rowcount > 0
