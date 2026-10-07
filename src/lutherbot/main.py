# src/lutherbot/main.py
import asyncio
import logging
import aiosqlite
import discord
from discord.ext import commands

from lutherbot import config
from lutherbot.cogs.chores import ThreadReviewView, ChoreManagerView, WeeklyAssignmentsView
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

    async def get_or_fetch_channel(
    self, channel_id: int
    ) -> discord.abc.GuildChannel | discord.Thread | None:
        if not channel_id:
            logger.warning(
                "get_or_fetch_channel called with invalid or empty ID: %r",
                channel_id,
            )
            return None

        # 1. Cache lookup
        ch = self.get_channel(channel_id)
        if ch:
            return ch

        # 2. API fetch with descriptive error logging
        try:
            return await self.fetch_channel(channel_id)
        except discord.Forbidden:
            logger.error(
                "Forbidden (403): Bot lacks 'View Channel' permission for channel ID %s.",
                channel_id,
            )
            return None
        except discord.NotFound:
            logger.error("NotFound (404): Channel ID %s does not exist.", channel_id)
            return None
        except discord.HTTPException as e:
            logger.error("HTTP error fetching channel ID %s: %s", channel_id, e)
            return None

    async def setup_hook(self):
        """Asynchronous initialization hook executed before the bot logs into Discord."""
        # 1. Establish SQLite connection and provision tables
        self._raw_db_conn = await aiosqlite.connect(config.DATABASE_PATH)
        self.db = Database(self._raw_db_conn)
        await self.db.init_tables()
        logger.info("Connected to SQLite and verified database schema.")

        # 2. Register all persistent Views (timeout=None)
        self.add_view(ThreadReviewView())
        self.add_view(MakeupBoardView(self))
        self.add_view(ShoppingBoardView(self))
        self.add_view(ChoreManagerView(self))
        self.add_view(WeeklyAssignmentsView(self))
        logger.info("Registered persistent UI views.")

        # 3. Load modular feature Cogs
        cogs = [
            "lutherbot.cogs.users",
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
        guild_id = getattr(config, "GUILD_ID", 0)
        if guild_id:
            guild_obj = discord.Object(id=guild_id)
            self.tree.copy_global_to(guild=guild_obj)
            synced = await self.tree.sync(guild=guild_obj)
            logger.info(
                f"Synced {len(synced)} command(s) locally to guild {guild_id}."
            )
        else:
            synced = await self.tree.sync()
            logger.info(
                f"Synced {len(synced)} application command(s) globally."
            )

    async def on_ready(self):
        """Triggered once the bot is connected and cached."""
        logger.info(f"Bot logged in successfully as {self.user} (ID: {self.user.id})")
        logger.info("LutherBot is active and listening for interactions.")
        print(f"Logged in as {self.user} (ID: {self.user.id})")  # Use self.user, not bot.user
        print("=" * 45)
        print("CONFIGURED CHANNEL IDS:")
        print(f"  FOOD_REQUEST_CHANNEL_ID: {config.FOOD_REQUEST_CHANNEL_ID} (type: {type(config.FOOD_REQUEST_CHANNEL_ID).__name__})")
        print(f"  FOOD_CHANNEL_ID:         {config.FOOD_CHANNEL_ID} (type: {type(config.FOOD_CHANNEL_ID).__name__})")
        print(f"  SUBMISSION_CHANNEL_ID:   {config.SUBMISSION_CHANNEL_ID} (type: {type(config.SUBMISSION_CHANNEL_ID).__name__})")
        print(f"  MAKEUP_CHANNEL_ID:       {getattr(config, 'MAKEUP_CHANNEL_ID', 'NOT FOUND')}")
        print("=" * 45)

    async def close(self):
        """Gracefully release resources when stopping or restarting."""
        if self._raw_db_conn:
            await self._raw_db_conn.close()
            logger.info("Closed SQLite connection pool.")
        await super().close()
        
def main():
    bot = LutherBot()
    token = getattr(config, "TOKEN", None) or getattr(config, "BOT_TOKEN", None)
    if not token:
        logger.warning("DISCORD_TOKEN is not set in environment or .env file.")
        return
    bot.run(token)


if __name__ == "__main__":
    main()
