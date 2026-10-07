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
    format_due_day,
)
from lutherbot.cogs.reviews import ThreadReviewView
from lutherbot.cogs.helpers import get_or_fetch_channel

class MakeupClaimSelect(discord.ui.Select):

    def __init__(self, makeups: list):
        options = [
            discord.SelectOption(
                label=f"#{m['mid']} {m['title'][:50]}",
                value=str(m["mid"]),
                description=f"Worth {m['hours']} missed chore hours",
            )
            for m in makeups[:25]
        ]
        super().__init__(
            placeholder="Select a bounty chore to claim...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        makeup_id = int(self.values[0])
        db = interaction.client.db

        claimed = await db.claim_makeup(makeup_id, interaction.user.id)
        if not claimed:
            await interaction.response.edit_message(
                content="❌ Someone claimed this bounty right before you! Please choose another.",
                view=None,
            )
            return

        await interaction.response.edit_message(
            content=(
                f"✅ **You claimed Makeup Chore #{makeup_id}!**\n"
                "When complete, run **`/chore_submit`** (or **`/submit_chores`**) to submit photo proof and spawn your review thread."
            ),
            view=None,
        )


class ChangeMakeupWeekModal(discord.ui.Modal, title="Switch Dashboard Week"):
    week_input = discord.ui.TextInput(
        label="Target Week Identifier",
        placeholder="e.g. 2026-W41",
        min_length=7,
        max_length=10,
        required=True,
    )

    def __init__(self, parent_view: "MakeupDashboardView"):
        super().__init__()
        self.parent_view = parent_view
        self.week_input.default = parent_view.week

    async def on_submit(self, interaction: discord.Interaction):
        new_w = self.week_input.value.strip().upper()
        if "-W" not in new_w:
            await interaction.response.send_message(
                "❌ Invalid week format. Please use ISO week format like `2026-W41`.",
                ephemeral=True,
            )
            return

        self.parent_view.week = new_w
        new_embed = await self.parent_view.build_dashboard_embed()
        await interaction.response.edit_message(embed=new_embed, view=self.parent_view)


class MakeupDashboardView(discord.ui.View):
    """Manager dashboard for viewing, adding, and removing makeup chore bounties by week."""
    

    def __init__(self, bot: commands.Bot, week: str | None = None):
        super().__init__(timeout=None)
        self.bot = bot
        self.week = week or get_iso_week()

    async def build_dashboard_embed(self) -> discord.Embed:
        makeups = await self.bot.db.get_makeups_by_week(self.week)

        embed = discord.Embed(
            title=f"🎛️ Makeup Chores Manager Dashboard",
            color=discord.Color.gold(),
            timestamp=datetime.utcnow(),
        )

        total = len(makeups)
        avail = sum(1 for m in makeups if m["status"] == "available")
        claimed = sum(1 for m in makeups if m["status"] in ("claimed", "under_review"))
        completed = sum(1 for m in makeups if m["status"] == "completed")

        embed.add_field(
            name="📅 Active Managing Week",
            value=f"**`{self.week}`**",
            inline=True,
        )
        embed.add_field(
            name="📊 Bounty Summary",
            value=f"Total: **{total}** (🟢 {avail} open | 🟡 {claimed} in-progress | ✅ {completed} settled)",
            inline=True,
        )

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
            for m in makeups[:20]:
                title = m["title"][:20] if len(m["title"]) > 20 else m["title"]
                status_short = m["status"][:10].upper()
                assignee = f"{m['first_name']} {m['last_name'][0]}." if m["first_name"] and m["last_name"] else (m["first_name"] or "—")
                lines.append(f"{m['mid']:<4} | {title:<22} | {m['hours']:<3} | {status_short:<11} | {assignee}")

            embed.description = (
                f"```text\n{chr(10).join(lines)}\n```\n"
                f"*Showing up to 20 bounties for week `{self.week}`. Select actions below:*"
            )

        return embed

    @discord.ui.button(
        label="Add Bounty",
        style=discord.ButtonStyle.success,
        emoji="➕",
        custom_id="mkup_dash_add",
        row=0,
    )
    async def add_bounty_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not check_is_manager(interaction.user, interaction.guild):
            await interaction.response.send_message(
                "⛔ **Restricted**: Only members with the **Manager** role can add makeup bounties.",
                ephemeral=True,
            )
            return

        chores = await self.bot.db.get_all_chores()
        if not chores:
            await interaction.response.send_message(
                "❌ No master chore templates found! Create chores in `/chore_manager` first.",
                ephemeral=True,
            )
            return

        options = [
            discord.SelectOption(
                label=f"#{c['cid']} {c['title'][:40]}",
                value=str(c["cid"]),
                description=f"{c['hours']}h credit • Due: {format_due_day(c['due_day'])}",
            )
            for c in chores[:25]
        ]

        pick_view = discord.ui.View(timeout=60)
        chore_select = discord.ui.Select(
            placeholder="Select a chore template from the list...",
            options=options,
        )

        async def chore_picked(s_inter: discord.Interaction):
            cid = int(chore_select.values[0])
            chore = await self.bot.db.get_chore(cid)
            mid = await self.bot.db.add_makeup_chore(cid, self.week)
            await s_inter.response.edit_message(
                content=f"✅ Added **{chore['title']}** ({chore['hours']}h) as Makeup Bounty **#{mid}** for week `{self.week}`!",
                view=None,
            )
            new_embed = await self.build_dashboard_embed()
            if interaction.message:
                await interaction.message.edit(embed=new_embed, view=self)

        chore_select.callback = chore_picked
        pick_view.add_item(chore_select)

        await interaction.response.send_message(
            f"Select a chore template below to spawn as a makeup bounty for week `{self.week}`:",
            view=pick_view,
            ephemeral=True,
        )

    @discord.ui.button(
        label="Remove Bounty",
        style=discord.ButtonStyle.danger,
        emoji="🗑️",
        custom_id="mkup_dash_remove",
        row=0,
    )
    async def remove_bounty_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not check_is_manager(interaction.user, interaction.guild):
            await interaction.response.send_message(
                "⛔ **Restricted**: Only members with the **Manager** role can remove makeup bounties.",
                ephemeral=True,
            )
            return

        makeups = await self.bot.db.get_makeups_by_week(self.week)
        available = [m for m in makeups if m["status"] == "available"]
        if not available:
            await interaction.response.send_message(
                f"❌ No available (unclaimed) makeup bounties to remove for week `{self.week}`.",
                ephemeral=True,
            )
            return

        options = [
            discord.SelectOption(
                label=f"#{m['mid']} {m['title'][:38]}",
                value=str(m["mid"]),
                description=f"{m['hours']}h credit • Status: {m['status'].upper()}",
            )
            for m in available[:25]
        ]

        pick_view = discord.ui.View(timeout=60)
        bounty_select = discord.ui.Select(
            placeholder="Select a bounty to delete...",
            options=options,
        )

        async def bounty_picked(s_inter: discord.Interaction):
            mid = int(bounty_select.values[0])
            deleted = await self.bot.db.delete_makeup_chore(mid)
            if deleted:
                await s_inter.response.edit_message(
                    content=f"🗑️ Deleted Makeup Bounty **#{mid}** from week `{self.week}`.",
                    view=None,
                )
                new_embed = await self.build_dashboard_embed()
                if interaction.message:
                    await interaction.message.edit(embed=new_embed, view=self)
            else:
                await s_inter.response.edit_message(
                    content=f"⚠️ Bounty #{mid} could not be removed (it may have been claimed).",
                    view=None,
                )

        bounty_select.callback = bounty_picked
        pick_view.add_item(bounty_select)

        await interaction.response.send_message(
            f"Select a bounty to delete from week `{self.week}`:",
            view=pick_view,
            ephemeral=True,
        )

    @discord.ui.button(
        label="Change Week",
        style=discord.ButtonStyle.primary,
        emoji="📅",
        custom_id="mkup_dash_week",
        row=0,
    )
    async def change_week_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not check_is_manager(interaction.user, interaction.guild):
            await interaction.response.send_message(
                "⛔ **Restricted**: Only managers can change the active week.",
                ephemeral=True,
            )
            return

        curr_w = get_iso_week()
        next_w = get_next_week(self.week)
        prev_w = get_prev_week(self.week)

        week_view = discord.ui.View(timeout=60)
        btn_curr = discord.ui.Button(label=f"Current ({curr_w})", style=discord.ButtonStyle.secondary)
        async def go_curr(c_inter: discord.Interaction):
            self.week = curr_w
            new_embed = await self.build_dashboard_embed()
            if interaction.message:
                await interaction.message.edit(embed=new_embed, view=self)
            await c_inter.response.send_message(f"Switched dashboard to `{curr_w}`.", ephemeral=True)
        btn_curr.callback = go_curr
        week_view.add_item(btn_curr)

        btn_next = discord.ui.Button(label=f"Next ({next_w})", style=discord.ButtonStyle.secondary)
        async def go_next(n_inter: discord.Interaction):
            self.week = next_w
            new_embed = await self.build_dashboard_embed()
            if interaction.message:
                await interaction.message.edit(embed=new_embed, view=self)
            await n_inter.response.send_message(f"Switched dashboard to `{next_w}`.", ephemeral=True)
        btn_next.callback = go_next
        week_view.add_item(btn_next)

        btn_prev = discord.ui.Button(label=f"Prev ({prev_w})", style=discord.ButtonStyle.secondary)
        async def go_prev(p_inter: discord.Interaction):
            self.week = prev_w
            new_embed = await self.build_dashboard_embed()
            if interaction.message:
                await interaction.message.edit(embed=new_embed, view=self)
            await p_inter.response.send_message(f"Switched dashboard to `{prev_w}`.", ephemeral=True)
        btn_prev.callback = go_prev
        week_view.add_item(btn_prev)

        btn_custom = discord.ui.Button(label="Custom Week...", style=discord.ButtonStyle.primary)
        async def go_custom(cust_inter: discord.Interaction):
            modal = ChangeMakeupWeekModal(self)
            await cust_inter.response.send_modal(modal)
        btn_custom.callback = go_custom
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
    async def post_board_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not check_is_manager(interaction.user, interaction.guild):
            await interaction.response.send_message(
                "⛔ **Restricted**: Only managers can post the bounty board.",
                ephemeral=True,
            )
            return
        makeup_channel = await get_or_fetch_channel(self.bot, config.MAKEUP_CHANNEL_ID)
        board_view = MakeupBoardView(self.bot)
        board_embed = await board_view.build_board_embed()
        await makeup_channel.send(embed=board_embed, view=board_view)
        await interaction.response.send_message(
            "✅ Public Makeup Bounty Board posted to the channel!",
            ephemeral=True,
        )

    @discord.ui.button(
        label="Refresh",
        style=discord.ButtonStyle.secondary,
        emoji="🔄",
        custom_id="mkup_dash_refresh",
        row=1,
    )
    async def refresh_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        new_embed = await self.build_dashboard_embed()
        await interaction.response.edit_message(embed=new_embed, view=self)


class MakeupBoardView(discord.ui.View):
    """Public board showing open makeup bounties that indebted housemates can claim."""

    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    async def build_board_embed(self) -> discord.Embed:
        available = await self.bot.db.get_available_makeups()

        embed = discord.Embed(
            title="🧹 Open Makeup Chore Bounties",
            color=discord.Color.gold(),
            timestamp=datetime.utcnow(),
        )

        if not available:
            embed.description = "```\nNo available makeup chores right now. You're all caught up!\n```"
            return embed

        lines = [
            f"{'ID':<4} | {'Chore':<24} | {'Hrs':<3} | {'Week':<8}",
            "-" * 45,
        ]
        for m in available:
            title = m["title"][:22] if len(m["title"]) > 22 else m["title"]
            lines.append(f"{m['mid']:<4} | {title:<24} | {m['hours']:<3} | {m['week']:<8}")

        embed.description = (
            f"```text\n{chr(10).join(lines)}\n```\n"
            "*Claim an open task to work off delinquent missed chore hours.\n"
            "Submit proof anytime using `/chore_submit` or `/submit_chores`.*"
        )
        return embed

    @discord.ui.button(
        label="Claim Bounty",
        style=discord.ButtonStyle.success,
        emoji="✋",
        custom_id="makeup_btn_claim",
        row=0,
    )
    async def claim_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
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
            await interaction.response.send_message(
                "There are no makeup chores currently available.", ephemeral=True
            )
            return

        view = discord.ui.View(timeout=60)
        view.add_item(MakeupClaimSelect(available))
        await interaction.response.send_message(
            f"You have `{debt} hrs` of missed debt. Pick a chore below:",
            view=view,
            ephemeral=True,
        )

    @discord.ui.button(
        label="Post Bounty",
        style=discord.ButtonStyle.secondary,
        emoji="➕",
        custom_id="makeup_btn_add_bounty",
        row=0,
    )
    async def add_bounty_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not check_is_manager(interaction.user, interaction.guild):
            await interaction.response.send_message(
                "⛔ **Restricted**: Only members with the **Manager** role can post makeup bounties.",
                ephemeral=True,
            )
            return

        chores = await self.bot.db.get_all_chores()
        if not chores:
            await interaction.response.send_message(
                "❌ No chore templates found. Create some in `/chore_manager` first.",
                ephemeral=True,
            )
            return

        options = [
            discord.SelectOption(
                label=f"#{c['cid']} {c['title'][:40]}",
                value=str(c["cid"]),
                description=f"{c['hours']}h credit • Due: {format_due_day(c['due_day'])}",
            )
            for c in chores[:25]
        ]

        select_view = discord.ui.View(timeout=60)
        chore_select = discord.ui.Select(
            placeholder="Pick a chore to spawn as a makeup bounty...",
            options=options,
        )

        async def chore_picked(s_inter: discord.Interaction):
            cid = int(chore_select.values[0])
            chore = await self.bot.db.get_chore(cid)
            current_week = get_iso_week()

            mid = await self.bot.db.add_makeup_chore(cid, current_week)
            await s_inter.response.edit_message(
                content=f"✅ Created Makeup Bounty **#{mid}** (`{chore['title']}` - {chore['hours']}h credit) for week `{current_week}`!",
                view=None,
            )
            new_embed = await self.build_board_embed()
            if interaction.message:
                await interaction.message.edit(embed=new_embed, view=self)

        chore_select.callback = chore_picked
        select_view.add_item(chore_select)

        await interaction.response.send_message(
            "Select a chore template to add as a makeup bounty:",
            view=select_view,
            ephemeral=True,
        )

    @discord.ui.button(
        label="Remove Bounty",
        style=discord.ButtonStyle.secondary,
        emoji="🗑️",
        custom_id="makeup_btn_remove_bounty",
        row=0,
    )
    async def remove_bounty_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not check_is_manager(interaction.user, interaction.guild):
            await interaction.response.send_message(
                "⛔ **Restricted**: Only members with the **Manager** role can remove makeup bounties.",
                ephemeral=True,
            )
            return

        available = await self.bot.db.get_available_makeups()
        if not available:
            await interaction.response.send_message(
                "❌ No available makeup bounties to remove.", ephemeral=True
            )
            return

        options = [
            discord.SelectOption(
                label=f"#{m['mid']} {m['title'][:40]}",
                value=str(m["mid"]),
                description=f"{m['hours']}h credit • Week: {m['week']}",
            )
            for m in available[:25]
        ]

        select_view = discord.ui.View(timeout=60)
        bounty_select = discord.ui.Select(
            placeholder="Select a bounty to delete from the board...",
            options=options,
        )

        async def bounty_picked(s_inter: discord.Interaction):
            mid = int(bounty_select.values[0])
            deleted = await self.bot.db.delete_makeup_chore(mid)
            if deleted:
                await s_inter.response.edit_message(
                    content=f"🗑️ Removed Makeup Bounty **#{mid}** from the board.",
                    view=None,
                )
                new_embed = await self.build_board_embed()
                if interaction.message:
                    await interaction.message.edit(embed=new_embed, view=self)
            else:
                await s_inter.response.edit_message(
                    content=f"⚠️ Bounty #{mid} could not be removed (it may have already been claimed).",
                    view=None,
                )

        bounty_select.callback = bounty_picked
        select_view.add_item(bounty_select)

        await interaction.response.send_message(
            "Select a bounty to remove:",
            view=select_view,
            ephemeral=True,
        )

    @discord.ui.button(
        label="Refresh Board",
        style=discord.ButtonStyle.secondary,
        emoji="🔄",
        custom_id="makeup_btn_refresh",
        row=1,
    )
    async def refresh_board(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        new_embed = await self.build_board_embed()
        await interaction.response.edit_message(embed=new_embed, view=self)


class MakeupsCog(commands.Cog):
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="makeup_dashboard",
        description="Manager: Interactive dashboard to manage makeup chore bounties for a week",
    )
    @app_commands.describe(week="Week identifier to manage (e.g. 2026-W41, defaults to current)")
    @app_commands.default_permissions(manage_guild=True)
    @has_manager_role()
    async def makeup_dashboard(
        self, interaction: discord.Interaction, week: str = ""
    ):
        worm_channel = await get_or_fetch_channel(self.bot, config.WORM_CHANNEL_ID)
        await interaction.response.defer(ephemeral=True)
        target_week = week.strip().upper() if week else get_iso_week()
        view = MakeupDashboardView(self.bot, week=target_week)
        embed = await view.build_dashboard_embed()
        await worm_channel.send(embed=embed, view=view)
        await interaction.followup.send("✅ Makeup Chores Dashboard posted!", ephemeral=True)

    @app_commands.command(
        name="makeup_post_board", description="Spawn the live makeup chore bounty board for members"
    )
    @app_commands.default_permissions(manage_guild=True)
    @has_manager_role()
    async def makeup_post_board(self, interaction: discord.Interaction):
        makeup_channel = await get_or_fetch_channel(self.bot, config.MAKEUP_CHANNEL_ID)
        await interaction.response.defer(ephemeral=True)
        view = MakeupBoardView(self.bot)
        embed = await view.build_board_embed()
        await makeup_channel.send(embed=embed, view=view)
        await interaction.followup.send("✅ Makeup board posted!", ephemeral=True)

    @app_commands.command(
        name="makeup_add", description="Manager: Add a chore template to the makeup pool for a week"
    )
    @app_commands.describe(
        chore="Chore template from list (autocomplete by title or select interactively)",
        week="Week identifier (e.g. 2026-W41, default current week)",
    )
    @app_commands.default_permissions(manage_guild=True)
    @has_manager_role()
    async def makeup_add(
        self,
        interaction: discord.Interaction,
        chore: str = "",
        week: str = "",
    ):
        target_week = week.strip().upper() if week else get_iso_week()

        if chore:
            cid = None
            if chore.isdigit():
                cid = int(chore)
            elif chore.startswith("#"):
                parts = chore[1:].split(maxsplit=1)
                if parts[0].isdigit():
                    cid = int(parts[0])

            if cid is not None:
                chore_obj = await self.bot.db.get_chore(cid)
                if chore_obj:
                    mid = await self.bot.db.add_makeup_chore(cid=cid, week=target_week)
                    await interaction.response.send_message(
                        f"✅ Created Makeup Bounty **#{mid}** (`{chore_obj['title']}` - {chore_obj['hours']}h credit) for week `{target_week}`.",
                        ephemeral=True,
                    )
                    return

        # If no chore specified or lookup not matched, open interactive select menu from master chore list
        chores = await self.bot.db.get_all_chores()
        if not chores:
            await interaction.response.send_message(
                "❌ No master chore templates found. Create chores in `/chore_manager` first.",
                ephemeral=True,
            )
            return

        options = [
            discord.SelectOption(
                label=f"#{c['cid']} {c['title'][:40]}",
                value=str(c["cid"]),
                description=f"{c['hours']}h credit • Due: {format_due_day(c['due_day'])}",
            )
            for c in chores[:25]
        ]

        pick_view = discord.ui.View(timeout=60)
        chore_select = discord.ui.Select(
            placeholder="Select a chore template to spawn as a bounty...",
            options=options,
        )

        async def chore_picked(s_inter: discord.Interaction):
            sel_cid = int(chore_select.values[0])
            c_data = await self.bot.db.get_chore(sel_cid)
            mid = await self.bot.db.add_makeup_chore(sel_cid, target_week)
            await s_inter.response.edit_message(
                content=f"✅ Created Makeup Bounty **#{mid}** (`{c_data['title']}` - {c_data['hours']}h credit) for week `{target_week}`!",
                view=None,
            )

        chore_select.callback = chore_picked
        pick_view.add_item(chore_select)
        await interaction.response.send_message(
            f"Select a chore from the list to add as a makeup bounty for week `{target_week}`:",
            view=pick_view,
            ephemeral=True,
        )

    @makeup_add.autocomplete("chore")
    async def makeup_add_chore_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        chores = await self.bot.db.get_all_chores()
        results = []
        for c in chores:
            display = f"#{c['cid']} {c['title']} ({c['hours']}h)"
            if current.lower() in display.lower() or not current:
                results.append(app_commands.Choice(name=display[:100], value=str(c["cid"])))
            if len(results) >= 25:
                break
        return results


async def setup(bot: commands.Bot):
    await bot.add_cog(MakeupsCog(bot))
