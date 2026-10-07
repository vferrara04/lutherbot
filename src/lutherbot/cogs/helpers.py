from datetime import datetime, date, timedelta
import discord
from discord import app_commands
from lutherbot import config
import logging
logger = logging.getLogger("lutherbot")

DAYS_OF_WEEK = {
    0: "Sunday",
    1: "Monday",
    2: "Tuesday",
    3: "Wednesday",
    4: "Thursday",
    5: "Friday",
    6: "Saturday",
}

DAY_NAME_TO_INT = {
    "sunday": 0, "sun": 0, "0": 0,
    "monday": 1, "mon": 1, "1": 1,
    "tuesday": 2, "tue": 2, "2": 2,
    "wednesday": 3, "wed": 3, "3": 3,
    "thursday": 4, "thu": 4, "4": 4,
    "friday": 5, "fri": 5, "5": 5,
    "saturday": 6, "sat": 6, "6": 6,
}

def format_due_day(due_day: int | None) -> str:
    """Returns human-friendly day of week name instead of integer."""
    if due_day is None:
        return "Any day"
    return DAYS_OF_WEEK.get(due_day, f"Day {due_day}")

def parse_due_day(val: str) -> int | None:
    """Parses day name or number into integer (0=Sunday ... 6=Saturday)."""
    cleaned = val.strip().lower()
    return DAY_NAME_TO_INT.get(cleaned, None)

def get_iso_week(dt: datetime | None = None) -> str:
    """Returns ISO week string like 2026-W41."""
    if dt is None:
        dt = datetime.now()
    year, week, _ = dt.isocalendar()
    return f"{year}-W{week:02d}"

def get_next_week(week_str: str) -> str:
    """Calculates the consecutive next ISO week string."""
    try:
        parts = week_str.split("-W")
        year = int(parts[0])
        week = int(parts[1])
        mon = date.fromisocalendar(year, week, 1) + timedelta(days=7)
        ny, nw, _ = mon.isocalendar()
        return f"{ny}-W{nw:02d}"
    except Exception:
        return week_str

def get_prev_week(week_str: str) -> str:
    """Calculates the previous ISO week string."""
    try:
        parts = week_str.split("-W")
        year = int(parts[0])
        week = int(parts[1])
        mon = date.fromisocalendar(year, week, 1) - timedelta(days=7)
        py, pw, _ = mon.isocalendar()
        return f"{py}-W{pw:02d}"
    except Exception:
        return week_str

def check_is_manager(user: discord.Member | discord.User, guild: discord.Guild | None) -> bool:
    """Checks whether the user has administrator permission or a manager role."""
    if not guild or not isinstance(user, discord.Member):
        return False

    if user.guild_permissions.administrator:
        return True

    role_id = getattr(config, "MANAGER_ROLE_ID", 0) or getattr(config, "WORM_ROLE_ID", 0)
    if role_id and any(r.id == role_id for r in user.roles):
        return True

    if any(r.name.lower() in ("manager", "chore manager", "worm", "admin") for r in user.roles):
        return True

    return False

def has_manager_role():
    """Restricts command execution strictly to members with the Manager role or Administrator permission."""
    async def predicate(interaction: discord.Interaction) -> bool:
        if check_is_manager(interaction.user, interaction.guild):
            return True

        await interaction.response.send_message(
            "⛔ **Restricted**: You must have the **Manager** role to use this command.",
            ephemeral=True,
        )
        return False

    return app_commands.check(predicate)

async def get_or_fetch_channel(
    client: discord.Client,
    channel_id: int,
) -> discord.abc.GuildChannel | discord.Thread | None:
    """Retrieves a channel from local cache or fetches it via the Discord REST API.

    Logs the exact Discord reason if the fetch fails.
    """
    if not channel_id:
        logger.warning(
            "get_or_fetch_channel was called with an invalid ID: %r", channel_id
        )
        return None

    # 1. Check local cache
    channel = client.get_channel(channel_id)
    if channel:
        return channel

    # 2. Fall back to API fetch
    try:
        return await client.fetch_channel(channel_id)
    except discord.Forbidden:
        logger.error(
            "Forbidden (403): Bot lacks 'View Channel' permission for channel ID %s.",
            channel_id,
        )
        return None
    except discord.NotFound:
        logger.error(
            "NotFound (404): Channel ID %s was not found in Discord.", channel_id
        )
        return None
    except discord.HTTPException as e:
        logger.error("HTTP error fetching channel ID %s: %s", channel_id, e)
        return None
