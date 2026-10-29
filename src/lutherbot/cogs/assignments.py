# src/lutherbot/cogs/assignments.py
from datetime import datetime
import discord
from discord.ext import commands
from lutherbot.cogs.helpers import (
    format_due_day,
    get_iso_week,
    get_next_week,
    get_prev_week,
    ensure_user_registered,
    make_chore_options,
    make_jump_view,
    PaginatedDashboardView,
    PaginatedSelectView,
)


class CustomRolloverModal(discord.ui.Modal, title="Custom Week Rollover"):

    def __init__(
        self,
        bot: commands.Bot,
        parent_view: "WeeklyAssignmentsView",
        default_old: str,
        default_new: str,
        dashboard_message: discord.Message | None = None,
    ):
        super().__init__()
        self.bot = bot
        self.parent_view = parent_view
        self.dashboard_message = dashboard_message
        self.old_week_input = discord.ui.TextInput(
            label="Old / Finalizing Week (e.g. 2026-W41)",
            default=default_old,
            min_length=6,
            max_length=10,
        )
        self.new_week_input = discord.ui.TextInput(
            label="New / Target Week (e.g. 2026-W42)",
            default=default_new,
            min_length=6,
            max_length=10,
        )
        self.add_item(self.old_week_input)
        self.add_item(self.new_week_input)

    async def on_submit(self, interaction: discord.Interaction):
        old_w = self.old_week_input.value.strip().upper()
        new_w = self.new_week_input.value.strip().upper()
        await interaction.parent_view._execute_rollover(
            interaction, old_w, new_w, self.dashboard_message
        ) if hasattr(interaction, "parent_view") else await self.parent_view._execute_rollover(
            interaction, old_w, new_w, self.dashboard_message
        )


class EditDebtModal(discord.ui.Modal):

    def __init__(self, bot: commands.Bot, user_id: int, user_data: dict):
        first = user_data.get("first_name", "")
        last = user_data.get("last_name", "")
        super().__init__(title=f"Edit Debt: {first} {last}"[:45])
        self.bot = bot
        self.user_id = user_id
        self.user_data = user_data

        curr = str(user_data.get("missed_chore_hours", 0))
        self.hours_input = discord.ui.TextInput(
            label="Missed Chore Debt Hours",
            default=curr,
            placeholder="Enter integer (e.g. 0 to clear, 2, 4...)",
            min_length=1,
            max_length=4,
        )
        self.reason_input = discord.ui.TextInput(
            label="Reason for adjustment",
            default="Manager adjustment",
            style=discord.TextStyle.short,
            required=False,
        )
        self.add_item(self.hours_input)
        self.add_item(self.reason_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            new_hours = max(0, int(self.hours_input.value.strip()))
        except ValueError:
            await interaction.response.send_message(
                "❌ Missed hours must be a valid integer number.", ephemeral=True
            )
            return

        old_hours = self.user_data.get("missed_chore_hours", 0)
        await self.bot.db.set_user_missed_hours(self.user_id, new_hours)

        name = f"{self.user_data.get('first_name', '')} {self.user_data.get('last_name', '')}".strip()
        reason = self.reason_input.value.strip() or "Manager adjustment"

        embed = discord.Embed(
            title="⏱️ Delinquent Debt Hours Adjusted",
            description=f"Updated hours for **{name}** (<@{self.user_id}>).",
            color=discord.Color.gold(),
            timestamp=datetime.utcnow(),
        )
        embed.add_field(name="Previous Debt", value=f"`{old_hours} hrs`", inline=True)
        embed.add_field(name="New Debt", value=f"`{new_hours} hrs`", inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.set_footer(text=f"Adjusted by {interaction.user.display_name}")

        await interaction.response.send_message(embed=embed, ephemeral=True)


class WeeklyAssignmentsView(PaginatedDashboardView):
    """Interactive manager dashboard to view, reassign, force approve, or delete weekly chores."""

    def __init__(self, bot: commands.Bot, week: str | None = None):
        super().__init__(bot=bot, per_page=15, manager_only=True, timeout=None)
        self.week = week or get_iso_week()

    def _get_current_week(self) -> str:
        return self.week or get_iso_week()

    async def build_embed(self, interaction: discord.Interaction | None = None) -> discord.Embed:
        return await self.build_assignments_embed()

    async def build_assignments_embed(self) -> discord.Embed:
        week = self._get_current_week()
        rows = await self.bot.db.get_weekly_assignments_detailed(week)

        embed = discord.Embed(
            title=f"📋 House Chore Assignments — Week `{week}`",
            description=(
                "Manage active chore assignments for each housemate.\n"
                "Use the buttons below to reassign, force-approve, add tasks, or remove assignments."
            ),
            color=discord.Color.blue(),
            timestamp=datetime.utcnow(),
        )

        if not rows:
            self.paginate([])
            embed.description = f"```\nNo chore assignments found for week {week}. Use 'Assign Task' or weekly rollover.\n```"
            return embed

        status_emojis = {
            "approved": "✅ APPROVED",
            "under_review": "⏳ REVIEW",
            "pending": "▫️ PENDING",
            "rejected": "❌ REDO",
            "missed": "⚠️ MISSED",
        }

        member_map: dict[str, list[str]] = {}
        for r in rows:
            member_name = f"{r['first_name']} {r['last_name']}"
            stat = status_emojis.get(r["status"], r["status"].upper())
            day_text = f"Due: {format_due_day(r['due_day'])}"
            item_line = f"• **{r['title']}** (`{r['hours']}h`) — `{stat}` ({day_text})"
            member_map.setdefault(member_name, []).append(item_line)

        page_members, total_pages = self.paginate(list(member_map.items()))

        for member, chore_lines in page_members:
            val_str = "\n".join(chore_lines)
            if len(val_str) > 1020:
                val_str = val_str[:1015] + "\n..."
            embed.add_field(name=f"👤 {member}", value=val_str, inline=False)

        embed.set_footer(
            text=f"Page {self.page + 1}/{total_pages} • Total active assignments: {len(rows)} • Managers only"
        )
        return embed

    @staticmethod
    def _make_assignment_options(rows: list, desc_fn) -> list[discord.SelectOption]:
        return [
            discord.SelectOption(
                label=f"{r['first_name']}: {r['title'][:25]}",
                value=f"{r['cid']}:{r['uid']}",
                description=desc_fn(r)[:100],
            )
            for r in rows
        ]

    async def _prompt_user_select(
        self,
        interaction: discord.Interaction,
        prompt_text: str,
        placeholder: str,
        on_user_picked,
    ):
        view = discord.ui.View(timeout=60)
        user_select = discord.ui.UserSelect(placeholder=placeholder, min_values=1, max_values=1)

        async def _cb(s_inter: discord.Interaction):
            target = user_select.values[0]
            await ensure_user_registered(self.bot.db, target)
            await on_user_picked(s_inter, target)

        user_select.callback = _cb
        view.add_item(user_select)
        await interaction.response.edit_message(content=prompt_text, view=view)

    # --- ROW 0: Task Management ---

    @discord.ui.button(
        label="Reassign Chore",
        style=discord.ButtonStyle.primary,
        emoji="✏️",
        custom_id="weekly_mgr_reassign",
        row=0,
    )
    async def reassign_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        week = self._get_current_week()
        rows = await self.bot.db.get_weekly_assignments_detailed(week)
        if not rows:
            await interaction.response.send_message("❌ No assignments to reassign.", ephemeral=True)
            return

        dashboard_msg = interaction.message
        options = self._make_assignment_options(rows, lambda r: f"{r['hours']}h • Status: {r['status']}")

        async def assignment_picked(s1_inter: discord.Interaction, selected_val: str):
            cid, old_uid = map(int, selected_val.split(":"))
            chore = await self.bot.db.get_chore(cid)

            async def on_new_user(s2_inter: discord.Interaction, new_member: discord.Member):
                await self.bot.db.reassign_chore(old_uid, new_member.id, cid, week)
                await s2_inter.response.edit_message(
                    content=f"✅ Reassigned **{chore['title']}** to {new_member.mention} for week `{week}`!",
                    view=None,
                )
                if dashboard_msg:
                    await dashboard_msg.edit(embed=await self.build_assignments_embed(), view=self)

            await self._prompt_user_select(
                s1_inter,
                f"Reassigning **{chore['title']}** ({chore['hours']}h). Who should get this chore?",
                "Step 2: Pick the new housemate to receive this chore...",
                on_new_user,
            )

        await interaction.response.send_message(
            "Select which housemate's assignment you want to change:",
            view=PaginatedSelectView(options, "Step 1: Select the assignment to move...", assignment_picked),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Set Status / Approve",
        style=discord.ButtonStyle.success,
        emoji="⚙️",
        custom_id="weekly_mgr_status",
        row=0,
    )
    async def edit_status_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        week = self._get_current_week()
        rows = await self.bot.db.get_weekly_assignments_detailed(week)
        if not rows:
            await interaction.response.send_message("❌ No assignments found.", ephemeral=True)
            return

        dashboard_msg = interaction.message
        options = self._make_assignment_options(rows, lambda r: f"Current: {r['status']}")

        async def assignment_picked(s1_inter: discord.Interaction, selected_val: str):
            cid, uid = map(int, selected_val.split(":"))
            chore = await self.bot.db.get_chore(cid)

            status_view = discord.ui.View(timeout=60)
            status_select = discord.ui.Select(
                placeholder="Pick new status...",
                options=[
                    discord.SelectOption(label="✅ Approved (Mark Done & Credit)", value="approved"),
                    discord.SelectOption(label="⏳ Under Review (Awaiting manager review)", value="under_review"),
                    discord.SelectOption(label="▫️ Pending (Not yet completed)", value="pending"),
                    discord.SelectOption(label="❌ Rejected (Needs Redo)", value="rejected"),
                    discord.SelectOption(label="⚠️ Missed (Delinquent debt)", value="missed"),
                ],
            )

            async def status_picked(s2_inter: discord.Interaction):
                new_stat = status_select.values[0]
                await self.bot.db.update_assignment_status(cid, uid, week, new_stat)
                await s2_inter.response.edit_message(
                    content=f"✅ Updated status of **{chore['title']}** to `{new_stat.upper()}`!",
                    view=None,
                )
                if dashboard_msg:
                    await dashboard_msg.edit(embed=await self.build_assignments_embed(), view=self)

            status_select.callback = status_picked
            status_view.add_item(status_select)
            await s1_inter.response.edit_message(
                content=f"Change status for **{chore['title']}**:",
                view=status_view,
            )

        await interaction.response.send_message(
            "Select an assignment to change status:",
            view=PaginatedSelectView(options, "Select assignment to change status...", assignment_picked),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Assign Task",
        style=discord.ButtonStyle.secondary,
        emoji="➕",
        custom_id="weekly_mgr_add_task",
        row=0,
    )
    async def add_task_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        chores = await self.bot.db.get_all_chores()
        if not chores:
            await interaction.response.send_message("❌ No master chores available.", ephemeral=True)
            return

        dashboard_msg = interaction.message

        async def chore_picked(s1_inter: discord.Interaction, selected_val: str):
            cid = int(selected_val)
            chore = await self.bot.db.get_chore(cid)
            week = self._get_current_week()

            async def on_user(s2_inter: discord.Interaction, target_user: discord.Member):
                await self.bot.db.assign_chore(cid, target_user.id, week)
                await self.bot.db.add_chore_template(cid, target_user.id)
                await s2_inter.response.edit_message(
                    content=f"✅ Assigned **{chore['title']}** to {target_user.mention} for week `{week}`!",
                    view=None,
                )
                if dashboard_msg:
                    await dashboard_msg.edit(embed=await self.build_assignments_embed(), view=self)

            await self._prompt_user_select(
                s1_inter,
                f"Assigning **{chore['title']}** ({chore['hours']}h). Who gets this chore?",
                "Step 2: Pick housemate to receive chore...",
                on_user,
            )

        await interaction.response.send_message(
            "Assign a chore for this week:",
            view=PaginatedSelectView(make_chore_options(chores), "Step 1: Pick chore to assign...", chore_picked),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Remove Assignment",
        style=discord.ButtonStyle.danger,
        emoji="🗑️",
        custom_id="weekly_mgr_remove_task",
        row=0,
    )
    async def remove_task_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        week = self._get_current_week()
        rows = await self.bot.db.get_weekly_assignments_detailed(week)
        if not rows:
            await interaction.response.send_message("❌ No assignments to remove.", ephemeral=True)
            return

        dashboard_msg = interaction.message
        options = self._make_assignment_options(rows, lambda _: f"Remove from week {week}")

        async def remove_picked(s_inter: discord.Interaction, selected_val: str):
            cid, uid = map(int, selected_val.split(":"))
            chore = await self.bot.db.get_chore(cid)
            await self.bot.db.delete_assignment(cid, uid, week)
            await s_inter.response.edit_message(
                content=f"🗑️ Removed assignment **{chore['title']}** from <@{uid}> for week `{week}`.",
                view=None,
            )
            if dashboard_msg:
                await dashboard_msg.edit(embed=await self.build_assignments_embed(), view=self)

        await interaction.response.send_message(
            "Select an assignment to remove:",
            view=PaginatedSelectView(options, "Select assignment to remove from this week...", remove_picked),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Makeup Bounties",
        style=discord.ButtonStyle.secondary,
        emoji="🧹",
        custom_id="weekly_mgr_makeups",
        row=0,
    )
    async def makeups_dashboard_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        from lutherbot.cogs.makeups import MakeupDashboardView
        view = MakeupDashboardView(self.bot, week=self._get_current_week())
        embed = await view.build_dashboard_embed()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    # --- ROW 1: Admin & Rollover Controls ---

    async def _execute_rollover(
        self,
        interaction: discord.Interaction,
        old_w: str,
        new_w: str,
        dashboard_msg: discord.Message | None,
    ):
        await interaction.response.defer(ephemeral=True)
        count = await self.bot.db.process_weekly_rollover(old_w, new_w)
        self.week = new_w
        self.page = 0
        result_embed = discord.Embed(
            title="🎉 Week Rolled Over Successfully!",
            description=(
                f"• **Finalized Week**: `{old_w}` (uncompleted chores recorded as missed debt)\n"
                f"• **Active New Week**: `{new_w}`\n"
                f"• **Assignments Provisioned**: **{count}** tasks"
            ),
            color=discord.Color.green(),
            timestamp=datetime.utcnow(),
        )
        await interaction.followup.send(embed=result_embed, ephemeral=True)
        if dashboard_msg:
            try:
                await dashboard_msg.edit(embed=await self.build_assignments_embed(), view=self)
            except discord.HTTPException:
                pass

    @discord.ui.button(
        label="Roll Over Week",
        style=discord.ButtonStyle.danger,
        emoji="⏩",
        custom_id="weekly_mgr_rollover",
        row=1,
    )
    async def rollover_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        current_week = self._get_current_week()
        next_week = get_next_week(current_week)
        prev_week = get_prev_week(current_week)
        dashboard_msg = interaction.message

        missing_now = await self.bot.db.get_missing_chores(current_week)
        missing_prev = await self.bot.db.get_missing_chores(prev_week)

        confirm_embed = discord.Embed(
            title="🔄 House Weekly Rollover",
            description=(
                "**Weekly rollover advances chore schedules and settles delinquent hours.**\n\n"
                "When you roll over:\n"
                "1. **Uncompleted Chores** (`pending` / `rejected`) in the departing week become **MISSED**.\n"
                "2. **Delinquent Debt Hours** are automatically added to the responsible members' accounts.\n"
                "3. **Makeup Bounties** are created manually by managers as needed.\n"
                "4. **New Week Assignments** are generated from recurring templates (or carried over)."
            ),
            color=discord.Color.orange(),
            timestamp=datetime.utcnow(),
        )
        confirm_embed.add_field(
            name=f"Current Week (`{current_week}`)",
            value=f"• Uncompleted tasks remaining: **{len(missing_now)}**\n• Next week will be: **`{next_week}`**",
            inline=False,
        )
        if missing_prev:
            confirm_embed.add_field(
                name=f"Previous Week (`{prev_week}`)",
                value=f"• Uncompleted tasks still open: **{len(missing_prev)}**",
                inline=False,
            )

        confirm_view = discord.ui.View(timeout=120)

        btn_curr = discord.ui.Button(
            label=f"Roll {current_week} ➔ {next_week}",
            style=discord.ButtonStyle.danger,
            emoji="⏩",
        )
        btn_curr.callback = lambda i: self._execute_rollover(i, current_week, next_week, dashboard_msg)
        confirm_view.add_item(btn_curr)

        if missing_prev:
            btn_prev = discord.ui.Button(
                label=f"Roll {prev_week} ➔ {current_week}",
                style=discord.ButtonStyle.primary,
                emoji="⏮️",
            )
            btn_prev.callback = lambda i: self._execute_rollover(i, prev_week, current_week, dashboard_msg)
            confirm_view.add_item(btn_prev)

        btn_custom = discord.ui.Button(label="Custom Weeks...", style=discord.ButtonStyle.secondary, emoji="⚙️")
        btn_custom.callback = lambda i: i.response.send_modal(
            CustomRolloverModal(self.bot, self, current_week, next_week, dashboard_message=dashboard_msg)
        )
        confirm_view.add_item(btn_custom)

        await interaction.response.send_message(embed=confirm_embed, view=confirm_view, ephemeral=True)

    @discord.ui.button(
        label="Pending Reviews",
        style=discord.ButtonStyle.secondary,
        emoji="📬",
        custom_id="weekly_mgr_pending_threads",
        row=1,
    )
    async def pending_threads_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._show_pending_reviews(interaction)

    @discord.ui.button(
        label="Edit Debt Hours",
        style=discord.ButtonStyle.secondary,
        emoji="⏱️",
        custom_id="weekly_mgr_edit_hours",
        row=1,
    )
    async def edit_hours_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        users = await self.bot.db.get_all_users()
        if not users:
            await interaction.response.send_message("❌ No housemates registered in the roster.", ephemeral=True)
            return

        options = [
            discord.SelectOption(
                label=f"{u['first_name']} {u['last_name']}",
                value=str(u["uid"]),
                description=f"Current Debt: {u['missed_chore_hours']} hrs",
            )
            for u in users
        ]

        async def user_selected(s_inter: discord.Interaction, selected_val: str):
            selected_uid = int(selected_val)
            user_data = await self.bot.db.get_user(selected_uid)
            await s_inter.response.send_modal(EditDebtModal(self.bot, selected_uid, dict(user_data)))

        await interaction.response.send_message(
            "Select which housemate's missed hours debt you want to adjust:",
            view=PaginatedSelectView(options, "Select housemate to edit debt hours...", user_selected),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Refresh",
        style=discord.ButtonStyle.secondary,
        emoji="🔄",
        custom_id="weekly_mgr_refresh",
        row=1,
    )
    async def refresh_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._refresh_display(interaction)

    # --- ROW 2: Dashboard Pagination ---

    @discord.ui.button(
        label="◀ Prev",
        style=discord.ButtonStyle.secondary,
        custom_id="weekly_mgr_prev_page",
        row=2,
    )
    async def prev_page_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._turn_page(interaction, -1)

    @discord.ui.button(
        label="Next ▶",
        style=discord.ButtonStyle.secondary,
        custom_id="weekly_mgr_next_page",
        row=2,
    )
    async def next_page_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._turn_page(interaction, 1)

    async def _show_pending_reviews(self, interaction: discord.Interaction):
        rows = await self.bot.db.get_pending_threads()
        if not rows:
            msg = "✅ **No chore submissions currently awaiting review!**\nAll submitted chores and bounties have been approved or resolved."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
            return

        embed = discord.Embed(
            title="📬 Pending Chore Review Queue",
            description=(
                f"There are **{len(rows)}** submission thread(s) waiting for manager review.\n"
                "Click the thread links or use the menu below to jump directly to any thread:"
            ),
            color=discord.Color.gold(),
            timestamp=datetime.utcnow(),
        )

        for i, r in enumerate(rows[:25]):
            type_label = "Bounty" if r["chore_type"] == "makeup" else "Chore"
            status_text = r["status"].replace("_", " ").upper()
            embed.add_field(
                name=f"{i+1}. {r['first_name']} {r['last_name']} — {r['title']} ({r['hours']}h)",
                value=f"Type: `{type_label}` | Week: `{r['week']}` | Status: `{status_text}`\nThread: <#{r['thread_id']}>",
                inline=False,
            )

        if len(rows) > 25:
            embed.set_footer(text=f"Showing top 25 of {len(rows)} in embed. Use the dropdown below to browse all {len(rows)} threads.")

        options = [
            discord.SelectOption(
                label=f"{r['first_name']}: {r['title'][:25]}",
                value=str(r["thread_id"]),
                description=f"{'Bounty' if r['chore_type'] == 'makeup' else 'Chore'} • {r['hours']}h • Week {r['week']}",
            )
            for r in rows
        ]

        async def select_thread(s_inter: discord.Interaction, selected_val: str):
            thread_id = int(selected_val)
            thread = interaction.guild.get_thread(thread_id) if interaction.guild else None
            jump_url = thread.jump_url if thread else f"https://discord.com/channels/{interaction.guild_id}/{thread_id}"
            await s_inter.response.send_message(
                f"🔗 Direct link to review thread <#{thread_id}>:",
                view=make_jump_view("Jump to Review Thread", jump_url),
                ephemeral=True,
            )

        view = PaginatedSelectView(options, "Select a review thread to jump to...", select_thread)
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)