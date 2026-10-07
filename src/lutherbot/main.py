# src/lutherbot/main.py
import asyncio
import logging
import aiosqlite
import discord
from discord.ext import commands

from lutherbot import config
from lutherbot.cogs.chores import ChoreDashboardView, ThreadReviewView
from lutherbot.cogs.makeups import MakeupBoardView
from lutherbot.cogs.shopping import ShoppingBoardView
from lutherbot.database.db import Database

# Configure structured logging for console output
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("lutherbot")


class LutherBot(commands.Bot):

    def __init__(self):
        # Configure required gateway intents
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True  # Required for reading uploaded attachments

        super().__init__(
            command_prefix="!",  # Slash commands primary; fallback prefix
            intents=intents,
            help_command=None,
        )
        self._raw_db_conn: aiosqlite.Connection | None = None
        self.db: Database | None = None

    async def setup_hook(self):
        """Asynchronous initialization hook executed before the bot logs into Discord."""
        # 1. Establish SQLite connection and provision tables
        self._raw_db_conn = await aiosqlite.connect(config.DATABASE_PATH)
        self.db = Database(self._raw_db_conn)
        await self.db.init_tables()
        logger.info("Connected to SQLite and verified database schema.")

        # 2. Register all persistent Views (timeout=None)
        # Allows buttons & select menus on existing messages/threads to work after reboots
        self.add_view(ChoreDashboardView(self))
        self.add_view(ThreadReviewView())
        self.add_view(MakeupBoardView(self))
        self.add_view(ShoppingBoardView(self))
        logger.info("Registered persistent UI views.")

        # 3. Load modular feature Cogs
        cogs = [
            "lutherbot.cogs.chores",
            "lutherbot.cogs.makeups",
            "lutherbot.cogs.shopping",
        ]
        for cog in cogs:
            try:
                await self.load_extension(cog)
                logger.info(f"Loaded extension: {cog}")
            except Exception as e:
                logger.exception(f"Failed to load extension {cog}: {e}")

        # 4. Synchronize application slash commands with Discord
        guild_id = getattr(config, "GUILD_ID", None)
        if guild_id:
            # Instant sync to a specific test/house server (no 1-hour global cache delay)
            guild_obj = discord.Object(id=guild_id)
            self.tree.copy_global_to(guild=guild_obj)
            synced = await self.tree.sync(guild=guild_obj)
            logger.info(
                f"Synced {len(synced)} command(s) locally to guild {guild_id}."
            )
        else:
            # Global sync across all servers
            synced = await self.tree.sync()
            logger.info(
                f"Synced {len(synced)} application command(s) globally."
            )

    async def on_ready(self):
        """Triggered once the bot is connected and cached."""
        logger.info(f"Bot logged in successfully as {self.user} (ID: {self.user.id})")
        logger.info("LutherBot is active and listening for interactions.")

    async def close(self):
        """Gracefully release resources when stopping or restarting."""
        if self._raw_db_conn:
            await self._raw_db_conn.close()
            logger.info("Closed SQLite connection pool.")
        await super().close()


def main():
    bot = LutherBot()
    bot.run(config.BOT_TOKEN)


if __name__ == "__main__":
    main()
