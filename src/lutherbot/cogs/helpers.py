# src/lutherbot/cogs/helpers.py
from datetime import datetime, date, timedelta
import logging
import math
from typing import Callable, Awaitable

import discord
from discord import app_commands
from discord.ext import commands
from lutherbot import config

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
    return DAY_NAME_TO_INT.get(val.strip().lower(), None)


def get_iso_week(dt: datetime | None = None) -> str:
    """Returns ISO week string like 2026-W41."""
    dt = dt or datetime.now()
    year, week, _ = dt.isocalendar()
    return f"{year}-W{week:02d}"


def _shift_iso_week(week_str: str, days: int) -> str:
    try:
        year_s, week_s = week_str.split("-W")
        target = date.fromisocalendar(int(year_s), int(week_s), 1) + timedelta(days=days)
        y, w, _ = target.isocalendar()
        return f"{y}-W{w:02d}"
    except Exception:
        return week_str


def get_next_week(week_str: str) -> str:
    """Calculates the consecutive next ISO week string."""
    return _shift_iso_week(week_str, 7)


def get_prev_week(week_str: str) -> str:
    """Calculates the previous ISO week string."""
    return _shift_iso_week(week_str, -7)


def check_is_manager(user: discord.Member | discord.User, guild: discord.Guild | None) -> bool:
    """Checks whether the user has administrator permission or a manager role."""
    if not guild or not isinstance(user, discord.Member):
        return False

    if user.guild_permissions.administrator:
        return True

    role_id = getattr(config, "MANAGER_ROLE_ID", 0) or getattr(config, "WORM_ROLE_ID", 0)
    if role_id and any(r.id == role_id for r in user.roles):
        return True

    return any(r.name.lower() in ("manager", "chore manager", "worm", "admin") for r in user.roles)


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
    """Retrieves a channel from local cache or fetches it via the Discord REST API."""
    if not channel_id:
        logger.warning("get_or_fetch_channel was called with an invalid ID: %r", channel_id)
        return None

    channel = client.get_channel(channel_id)
    if channel:
        return channel

    try:
        return await client.fetch_channel(channel_id)
    except discord.Forbidden:
        logger.error("Forbidden (403): Bot lacks 'View Channel' permission for channel ID %s.", channel_id)
    except discord.NotFound:
        logger.error("NotFound (404): Channel ID %s was not found in Discord.", channel_id)
    except discord.HTTPException as e:
        logger.error("HTTP error fetching channel ID %s: %s", channel_id, e)
    return None


# =============================================================================
# Shared UI & Database Helpers
# =============================================================================


async def send_or_edit(
    interaction: discord.Interaction,
    content: str,
    view: discord.ui.View | None = None,
):
    """Safely sends or edits an ephemeral response regardless of interaction state."""
    if interaction.response.is_done():
        await interaction.followup.send(content, view=view, ephemeral=True)
    elif interaction.message is not None:
        await interaction.response.edit_message(content=content, embed=None, view=view)
    else:
        await interaction.response.send_message(content, view=view, ephemeral=True)


def make_jump_view(label: str, url: str, emoji: str = "🔗") -> discord.ui.View:
    """Creates a single-button link view for jumping directly to a thread."""
    view = discord.ui.View()
    view.add_item(
        discord.ui.Button(
            label=label[:80],
            url=url,
            style=discord.ButtonStyle.link,
            emoji=emoji,
        )
    )
    return view


async def ensure_user_registered(db, member: discord.Member | discord.User, default_debt: int = 0) -> dict:
    """Ensures a Discord member exists in the users table, auto-registering their display name if needed."""
    user = await db.get_user(member.id)
    if not user:
        parts = member.display_name.split()
        f_name = parts[0] if parts else member.name
        l_name = " ".join(parts[1:]) if len(parts) > 1 else ""
        await db.upsert_user(member.id, f_name, l_name, default_debt)
        user = await db.get_user(member.id)
    return user


def make_chore_options(chores: list, mode: str = "default") -> list[discord.SelectOption]:
    """Builds standardized SelectOptions for master chore lists."""
    options = []
    for c in chores:
        if mode == "delete":
            desc = f"Delete #{c['cid']} ({c['hours']}h)"
        else:
            desc = f"{c['hours']}h credit • Due: {format_due_day(c['due_day'])}"
        options.append(
            discord.SelectOption(
                label=f"#{c['cid']} {c['title'][:40]}",
                value=str(c["cid"]),
                description=desc[:100],
            )
        )
    return options


async def chore_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[int]]:
    """Shared autocomplete for integer chore_id parameters."""
    chores = await interaction.client.db.get_all_chores()
    results = []
    for c in chores:
        display = f"#{c['cid']} {c['title']} ({c['hours']}h)"
        if not current or current.lower() in display.lower():
            results.append(app_commands.Choice(name=display[:100], value=int(c["cid"])))
        if len(results) >= 25:
            break
    return results


async def post_dashboard_to_channel(
    interaction: discord.Interaction,
    channel_id: int,
    view: discord.ui.View,
    embed: discord.Embed,
    confirm_msg: str,
):
    """Spawns a dashboard view into a configured target channel and replies ephemerally."""
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)
    channel = await get_or_fetch_channel(interaction.client, channel_id)
    if not channel:
        await interaction.followup.send("❌ Target channel not found or inaccessible.", ephemeral=True)
        return
    await channel.send(embed=embed, view=view)
    await interaction.followup.send(confirm_msg, ephemeral=True)


class PaginatedDashboardView(discord.ui.View):
    """Base view for paginated embed dashboards.

    Subclasses should implement `async def build_embed(self, interaction=None) -> discord.Embed`
    and call `self.paginate(items)` inside it. Any button whose custom_id ends with
    `_prev` or `_next` is automatically enabled/disabled based on the current page.
    """

    def __init__(
        self,
        bot: commands.Bot | None = None,
        per_page: int = 15,
        manager_only: bool = False,
        timeout: float | None = None,
    ):
        super().__init__(timeout=timeout)
        self.bot = bot
        self.page = 0
        self.per_page = per_page
        self.manager_only = manager_only

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.manager_only and not check_is_manager(interaction.user, interaction.guild):
            await interaction.response.send_message(
                "⛔ **Restricted**: Only members with the **Manager** role can use these controls.",
                ephemeral=True,
            )
            return False
        return True

    def paginate(self, items: list) -> tuple[list, int]:
        """Returns (page_slice, total_pages) and updates Prev/Next button states."""
        total_pages = max(1, math.ceil(len(items) / self.per_page))
        self.page = max(0, min(self.page, total_pages - 1))

        for child in self.children:
            if isinstance(child, discord.ui.Button):
                cid = child.custom_id or ""
                if cid.endswith("_prev") or cid.endswith("_prev_page") or child.label == "◀ Prev":
                    child.disabled = self.page <= 0
                elif cid.endswith("_next") or cid.endswith("_next_page") or child.label == "Next ▶":
                    child.disabled = self.page >= total_pages - 1

        start = self.page * self.per_page
        return items[start : start + self.per_page], total_pages

    async def build_embed(self, interaction: discord.Interaction | None = None) -> discord.Embed:
        raise NotImplementedError

    async def _refresh_display(self, interaction: discord.Interaction):
        embed = await self.build_embed(interaction)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _turn_page(self, interaction: discord.Interaction, delta: int):
        self.page = max(0, self.page + delta)
        await self._refresh_display(interaction)


class PaginatedSelectView(discord.ui.View):
    """Universal view that paginates any list of SelectOptions 25 items at a time."""

    def __init__(
        self,
        options: list[discord.SelectOption],
        placeholder: str,
        on_select: Callable[[discord.Interaction, str], Awaitable[None]],
        timeout: float = 120,
    ):
        super().__init__(timeout=timeout)
        self.all_options = options
        self.base_placeholder = placeholder
        self.on_select = on_select
        self.page = 0
        self.per_page = 25
        self.total_pages = max(1, math.ceil(len(self.all_options) / self.per_page))
        self._rebuild()

    def _rebuild(self):
        self.clear_items()
        start = self.page * self.per_page
        chunk = self.all_options[start : start + self.per_page]

        if self.total_pages > 1:
            ph = f"{self.base_placeholder[:110]} (Page {self.page + 1}/{self.total_pages})"
        else:
            ph = self.base_placeholder[:150]

        select = discord.ui.Select(placeholder=ph, options=chunk, row=0)
        select.callback = self._handle_select
        self.add_item(select)

        if self.total_pages > 1:
            prev_btn = discord.ui.Button(
                label="◀ Prev",
                style=discord.ButtonStyle.secondary,
                disabled=(self.page <= 0),
                row=1,
            )
            prev_btn.callback = self._prev_page
            self.add_item(prev_btn)

            indicator = discord.ui.Button(
                label=f"Page {self.page + 1}/{self.total_pages}",
                style=discord.ButtonStyle.secondary,
                disabled=True,
                row=1,
            )
            self.add_item(indicator)

            next_btn = discord.ui.Button(
                label="Next ▶",
                style=discord.ButtonStyle.secondary,
                disabled=(self.page >= self.total_pages - 1),
                row=1,
            )
            next_btn.callback = self._next_page
            self.add_item(next_btn)

    async def _prev_page(self, interaction: discord.Interaction):
        if self.page > 0:
            self.page -= 1
            self._rebuild()
            await interaction.response.edit_message(view=self)
        else:
            await interaction.response.defer()

    async def _next_page(self, interaction: discord.Interaction):
        if self.page < self.total_pages - 1:
            self.page += 1
            self._rebuild()
            await interaction.response.edit_message(view=self)
        else:
            await interaction.response.defer()

    async def _handle_select(self, interaction: discord.Interaction):
        await self.on_select(interaction, interaction.data["values"][0])