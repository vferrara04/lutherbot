# src/lutherbot/cogs/makeups.py
from datetime import datetime
import discord
from discord import app_commands
from discord.ext import commands
from lutherbot import config
from lutherbot.cogs.helpers import (
    has_manager_role,
    check_is_manager,
    get_iso_week,
    get_next_week,
    get_prev_week,
    make_chore_options,
    post_dashboard_to_channel,
    PaginatedDashboardView,
    PaginatedSelectView,
)


async def prompt_add_makeup_bounty(
    interaction: discord.Interaction,
    bot: commands.Bot,
    week: str,
    on_done=None,
):
    """Shared flow for selecting a master chore template and spawning it as a makeup bounty."""
    chores = await bot.db.get_all_chores()
    if not chores:
        await interaction.response.send_message(
            "❌ No master chore templates found! Create chores in `/chore_manager` first.",
            ephemeral=True,
        )
        return

    async def chore_picked(s_inter: discord.Interaction, selected_val: str):
        cid = int(selected_val)
        chore = await bot.db.get_chore(cid)
        mid = await bot.db.add_makeup_chore(cid, week)
        await s_inter.response.edit_message(
            content=f"✅ Created Makeup Bounty **#{mid}** (`{chore['title']}` - {chore['hours']}h credit) for week `{week}`!",
            view=None,
        )
        if on_done:
            await on_done()

    await interaction.response.send_message(
        f"Select a chore template to spawn as a makeup bounty for week `{week}`:",
        view=PaginatedSelectView(
            make_chore_options(chores),
            "Select a chore template from the list...",
            chore_picked,
        ),
        ephemeral=True,
    )


async def prompt_remove_makeup_bounty(
    interaction: discord.Interaction,
    bot: commands.Bot,
    available: list,
    on_done=None,
):
    """Shared flow for deleting an unclaimed makeup bounty."""
    if not available:
        await interaction.response.send_message(
            "❌ No available (unclaimed) makeup bounties to remove.",
            ephemeral=True,
        )
        return

    options = [
        discord.SelectOption(
            label=f"#{m['mid']} {m['title'][:38]}",
            value=str(m["mid"]),
            description=f"{m['hours']}h credit • Week: {m['week']}",
        )
        for m in available
    ]

    async def bounty_picked(s_inter: discord.Interaction, selected_val: str):
        mid = int(selected_val)
        deleted = await bot.db.delete_makeup_chore(mid)
        if deleted:
            await s_inter.response.edit_message(
                content=f"🗑️ Deleted Makeup Bounty **#{mid}**.",
                view=None,
            )
            if on_done:
                await on_done()
        else:
            await s_inter.response.edit_message(
                content=f"⚠️ Bounty #{mid} could not be removed (it may have already been claimed).",
                view=None,
            )

    await interaction.response.send_message(
        "Select a bounty to remove:",
        view=PaginatedSelectView(options, "Select a bounty to delete...", bounty_picked),
        ephemeral=True,
    )


class ChangeMakeupWeekModal(discord.ui.Modal, title="Switch Dashboard Week"):
    week_input = discord.ui.TextInput(
        label="Target Week Identifier",
        placeholder="e.g. 2026-W41",
        min_length=7,
        max_length=10,
        required=True,
    )

    def __init__(self, parent_view: "MakeupDashboardView", dashboard_message: discord.Message | None = None):
        super().__init__()
        self.parent_view = parent_view
        self.dashboard_message = dashboard_message
        self.week_input.default = parent_view.week

    async def on_submit(self, interaction: discord.Interaction):
        new_w = self.week_input.value.strip().upper()
        if "-W" not in new_w:
            await interaction.response.send_message(
                "❌ Invalid week format. Please use ISO week format like `2026-W41`.",
                ephemeral=True,
            )
            return

        await self.parent_view._switch_week(interaction, new_w, self.dashboard_message, is_modal=True)


class MakeupDashboardView(PaginatedDashboardView):
    """Manager dashboard for viewing, adding, and removing makeup chore bounties by week."""

    def __init__(self, bot: commands.Bot, week: str | None = None):
        super().__init__(bot=bot, per_page=20, manager_only=True, timeout=None)
        self.week = week or get_iso_week()

    async def build_embed(self, interaction: discord.Interaction | None = None) -> discord.Embed:
        return await self.build_dashboard_embed()

    async def build_dashboard_embed(self) -> discord.Embed:
        makeups = await self.bot.db.get_makeups_by_week(self.week)

        embed = discord.Embed(
            title="🎛️ Makeup Chores Manager Dashboard",
            color=discord.Color.gold(),
            timestamp=datetime.utcnow(),
        )

        total = len(makeups)
        avail = sum(1 for m in makeups if m["status"] == "available")
        claimed = sum(1 for m in makeups if m["status"] in ("claimed", "under_review"))
        completed = sum(1 for m in makeups if m["status"] == "completed")

        embed.add_field(name="📅 Active Managing Week", value=f"**`{self.week}`**", inline=True)
        embed.add_field(
            name="📊 Bounty Summary",
            value=f"Total: **{total}** (🟢 {avail} open | 🟡 {claimed} in-progress | ✅ {completed} settled)",
            inline=True,
        )

        chunk, total_pages = self.paginate(makeups)
        if not makeups:
            embed.description = (
                f"```text\nNo makeup chore bounties configured for week {self.week}.\n"
                "Click '➕ Add Bounty' below to select from your master chore templates!\n```"
            )
        else:
            lines = [
                f"{'ID':<4} | {'Chore':<22} | {'Hrs':<3} | {'Status':<11} | {'Member'}",
                "-" * 58,
            ]
            for m in chunk:
                title = m["title"][:20]
                status_short = m["status"][:10].upper()
                assignee = (
                    f"{m['first_name']} {m['last_name'][0]}."
                    if m["first_name"] and m["last_name"]
                    else (m["first_name"] or "—")
                )
                lines.append(f"{m['mid']:<4} | {title:<22} | {m['hours']:<3} | {status_short:<11} | {assignee}")

            embed.description = (
                f"```text\n{chr(10).join(lines)}\n```\n"
                f"*Page {self.page + 1}/{total_pages} ({total} total bounties for week `{self.week}`)*"
            )

        return embed

    async def _refresh_board_msg(self, msg: discord.Message | None):
        if msg:
            await msg.edit(embed=await self.build_dashboard_embed(), view=self)

    @discord.ui.button(
        label="Add Bounty",
        style=discord.ButtonStyle.success,
        emoji="➕",
        custom_id="mkup_dash_add",
        row=0,
    )
    async def add_bounty_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        msg = interaction.message
        await prompt_add_makeup_bounty(
            interaction, self.bot, self.week, on_done=lambda: self._refresh_board_msg(msg)
        )

    @discord.ui.button(
        label="Remove Bounty",
        style=discord.ButtonStyle.danger,
        emoji="🗑️",
        custom_id="mkup_dash_remove",
        row=0,
    )
    async def remove_bounty_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        makeups = await self.bot.db.get_makeups_by_week(self.week)
        available = [m for m in makeups if m["status"] == "available"]
        msg = interaction.message
        await prompt_remove_makeup_bounty(
            interaction, self.bot, available, on_done=lambda: self._refresh_board_msg(msg)
        )

    async def _switch_week(
        self,
        interaction: discord.Interaction,
        target_week: str,
        dashboard_msg: discord.Message | None,
        is_modal: bool = False,
    ):
        self.week = target_week
        self.page = 0
        await self._refresh_board_msg(dashboard_msg)
        if is_modal:
            await interaction.response.send_message(f"✅ Switched dashboard to `{target_week}`.", ephemeral=True)
        else:
            await interaction.response.edit_message(content=f"✅ Switched dashboard to `{target_week}`.", view=None)

    @discord.ui.button(
        label="Change Week",
        style=discord.ButtonStyle.primary,
        emoji="📅",
        custom_id="mkup_dash_week",
        row=0,
    )
    async def change_week_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        curr_w = get_iso_week()
        next_w = get_next_week(self.week)
        prev_w = get_prev_week(self.week)
        dashboard_msg = interaction.message

        week_view = discord.ui.View(timeout=60)
        for label, wk in [("Current", curr_w), ("Next", next_w), ("Prev", prev_w)]:
            btn = discord.ui.Button(label=f"{label} ({wk})", style=discord.ButtonStyle.secondary)
            btn.callback = lambda i, w=wk: self._switch_week(i, w, dashboard_msg)
            week_view.add_item(btn)

        btn_custom = discord.ui.Button(label="Custom Week...", style=discord.ButtonStyle.primary)
        btn_custom.callback = lambda i: i.response.send_modal(
            ChangeMakeupWeekModal(self, dashboard_message=dashboard_msg)
        )
        week_view.add_item(btn_custom)

        await interaction.response.send_message(
            f"Select a week to manage for makeup chore bounties (Currently: `{self.week}`):",
            view=week_view,
            ephemeral=True,
        )

    @discord.ui.button(
        label="Post Bounty Board",
        style=discord.ButtonStyle.secondary,
        emoji="📌",
        custom_id="mkup_dash_post_board",
        row=1,
    )
    async def post_board_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        board_view = MakeupBoardView(self.bot)
        board_embed = await board_view.build_board_embed()
        await post_dashboard_to_channel(
            interaction,
            config.MAKEUP_CHANNEL_ID,
            board_view,
            board_embed,
            "✅ Public Makeup Bounty Board posted to the channel!",
        )

    @discord.ui.button(
        label="Refresh",
        style=discord.ButtonStyle.secondary,
        emoji="🔄",
        custom_id="mkup_dash_refresh",
        row=1,
    )
    async def refresh_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._refresh_display(interaction)

    @discord.ui.button(
        label="◀ Prev",
        style=discord.ButtonStyle.secondary,
        custom_id="mkup_dash_prev_page",
        row=1,
    )
    async def prev_page_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._turn_page(interaction, -1)

    @discord.ui.button(
        label="Next ▶",
        style=discord.ButtonStyle.secondary,
        custom_id="mkup_dash_next_page",
        row=1,
    )
    async def next_page_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._turn_page(interaction, 1)


class MakeupBoardView(PaginatedDashboardView):
    """Public board showing open makeup bounties that indebted housemates can claim."""

    def __init__(self, bot: commands.Bot):
        super().__init__(bot=bot, per_page=20, manager_only=False, timeout=None)

    async def build_embed(self, interaction: discord.Interaction | None = None) -> discord.Embed:
        return await self.build_board_embed()

    async def build_board_embed(self) -> discord.Embed:
        available = await self.bot.db.get_available_makeups()

        embed = discord.Embed(
            title="🧹 Open Makeup Chore Bounties",
            color=discord.Color.gold(),
            timestamp=datetime.utcnow(),
        )

        chunk, total_pages = self.paginate(available)
        if not available:
            embed.description = "```\nNo available makeup chores right now. You're all caught up!\n```"
            return embed

        lines = [
            f"{'ID':<4} | {'Chore':<24} | {'Hrs':<3} | {'Week':<8}",
            "-" * 45,
        ]
        for m in chunk:
            lines.append(f"{m['mid']:<4} | {m['title'][:22]:<24} | {m['hours']:<3} | {m['week']:<8}")

        embed.description = (
            f"```text\n{chr(10).join(lines)}\n```\n"
            f"*Page {self.page + 1}/{total_pages} ({len(available)} open bounties) • Claim an open task to work off delinquent missed chore hours.\n"
            "Submit proof anytime using `/chore_submit`.*"
        )
        return embed

    async def _refresh_board_msg(self, msg: discord.Message | None):
        if msg:
            await msg.edit(embed=await self.build_board_embed(), view=self)

    @discord.ui.button(
        label="Claim Bounty",
        style=discord.ButtonStyle.success,
        emoji="✋",
        custom_id="makeup_btn_claim",
        row=0,
    )
    async def claim_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = await self.bot.db.get_user(interaction.user.id)
        debt = user["missed_chore_hours"] if user else 0

        if debt <= 0:
            await interaction.response.send_message(
                "✨ You have 0 missed chore hours! Save these bounties for members with debt.",
                ephemeral=True,
            )
            return

        available = await self.bot.db.get_available_makeups()
        if not available:
            await interaction.response.send_message("There are no makeup chores currently available.", ephemeral=True)
            return

        board_msg = interaction.message
        options = [
            discord.SelectOption(
                label=f"#{m['mid']} {m['title'][:50]}",
                value=str(m["mid"]),
                description=f"Worth {m['hours']} missed chore hours",
            )
            for m in available
        ]

        async def claim_selected(s_inter: discord.Interaction, selected_val: str):
            makeup_id = int(selected_val)
            claimed = await self.bot.db.claim_makeup(makeup_id, s_inter.user.id)
            if not claimed:
                await s_inter.response.edit_message(
                    content="❌ Someone claimed this bounty right before you! Please choose another.",
                    view=None,
                )
                return

            await s_inter.response.edit_message(
                content=(
                    f"✅ **You claimed Makeup Chore #{makeup_id}!**\n"
                    "When complete, run **`/chore_submit`** to submit photo proof and spawn your review thread."
                ),
                view=None,
            )
            await self._refresh_board_msg(board_msg)

        await interaction.response.send_message(
            f"You have `{debt} hrs` of missed debt. Pick a chore below:",
            view=PaginatedSelectView(options, "Select a bounty chore to claim...", claim_selected),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Post Bounty",
        style=discord.ButtonStyle.secondary,
        emoji="➕",
        custom_id="makeup_btn_add_bounty",
        row=0,
    )
    async def add_bounty_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not check_is_manager(interaction.user, interaction.guild):
            await interaction.response.send_message(
                "⛔ **Restricted**: Only members with the **Manager** role can post makeup bounties.",
                ephemeral=True,
            )
            return

        msg = interaction.message
        await prompt_add_makeup_bounty(
            interaction, self.bot, get_iso_week(), on_done=lambda: self._refresh_board_msg(msg)
        )

    @discord.ui.button(
        label="Remove Bounty",
        style=discord.ButtonStyle.secondary,
        emoji="🗑️",
        custom_id="makeup_btn_remove_bounty",
        row=0,
    )
    async def remove_bounty_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not check_is_manager(interaction.user, interaction.guild):
            await interaction.response.send_message(
                "⛔ **Restricted**: Only members with the **Manager** role can remove makeup bounties.",
                ephemeral=True,
            )
            return

        available = await self.bot.db.get_available_makeups()
        msg = interaction.message
        await prompt_remove_makeup_bounty(
            interaction, self.bot, available, on_done=lambda: self._refresh_board_msg(msg)
        )

    @discord.ui.button(
        label="Refresh Board",
        style=discord.ButtonStyle.secondary,
        emoji="🔄",
        custom_id="makeup_btn_refresh",
        row=1,
    )
    async def refresh_board(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._refresh_display(interaction)

    @discord.ui.button(
        label="◀ Prev",
        style=discord.ButtonStyle.secondary,
        custom_id="makeup_btn_prev_page",
        row=1,
    )
    async def prev_page_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._turn_page(interaction, -1)

    @discord.ui.button(
        label="Next ▶",
        style=discord.ButtonStyle.secondary,
        custom_id="makeup_btn_next_page",
        row=1,
    )
    async def next_page_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._turn_page(interaction, 1)


class MakeupsCog(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="makeup_dashboard",
        description="Manager: Interactive dashboard to manage makeup chore bounties for a week",
    )
    @app_commands.describe(week="Week identifier to manage (e.g. 2026-W41, defaults to current)")
    @has_manager_role()
    async def makeup_dashboard(self, interaction: discord.Interaction, week: str = ""):
        target_week = week.strip().upper() if week else get_iso_week()
        view = MakeupDashboardView(self.bot, week=target_week)
        embed = await view.build_dashboard_embed()
        await post_dashboard_to_channel(
            interaction, config.WORM_CHANNEL_ID, view, embed, "✅ Makeup Chores Dashboard posted!"
        )

    @app_commands.command(
        name="makeup_post_board",
        description="Spawn the live makeup chore bounty board for members",
    )
    @has_manager_role()
    async def makeup_post_board(self, interaction: discord.Interaction):
        view = MakeupBoardView(self.bot)
        embed = await view.build_board_embed()
        await post_dashboard_to_channel(
            interaction, config.MAKEUP_CHANNEL_ID, view, embed, "✅ Makeup board posted!"
        )

    @app_commands.command(
        name="makeup_add",
        description="Manager: Add a chore template to the makeup pool for a week",
    )
    @app_commands.describe(
        chore="Chore template from list (autocomplete by title or select interactively)",
        week="Week identifier (e.g. 2026-W41, default current week)",
    )
    @has_manager_role()
    async def makeup_add(self, interaction: discord.Interaction, chore: str = "", week: str = ""):
        target_week = week.strip().upper() if week else get_iso_week()

        if chore:
            cleaned = chore.lstrip("#").split(maxsplit=1)[0]
            if cleaned.isdigit():
                cid = int(cleaned)
                chore_obj = await self.bot.db.get_chore(cid)
                if chore_obj:
                    mid = await self.bot.db.add_makeup_chore(cid=cid, week=target_week)
                    await interaction.response.send_message(
                        f"✅ Created Makeup Bounty **#{mid}** (`{chore_obj['title']}` - {chore_obj['hours']}h credit) for week `{target_week}`.",
                        ephemeral=True,
                    )
                    return

        await prompt_add_makeup_bounty(interaction, self.bot, target_week)

    @makeup_add.autocomplete("chore")
    async def makeup_add_chore_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        chores = await self.bot.db.get_all_chores()
        results = []
        for c in chores:
            display = f"#{c['cid']} {c['title']} ({c['hours']}h)"
            if not current or current.lower() in display.lower():
                results.append(app_commands.Choice(name=display[:100], value=str(c["cid"])))
            if len(results) >= 25:
                break
        return results


async def setup(bot: commands.Bot):
    await bot.add_cog(MakeupsCog(bot))