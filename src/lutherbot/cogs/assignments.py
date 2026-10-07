# src/lutherbot/cogs/assignments.py
from datetime import datetime
import discord
from discord import app_commands
from discord.ext import commands
from lutherbot.cogs.helpers import (
    check_is_manager,
    has_manager_role,
    format_due_day,
    get_iso_week,
    get_next_week,
    get_prev_week,
)


class CustomRolloverModal(discord.ui.Modal, title="Custom Week Rollover"):
    def __init__(self, bot: commands.Bot, parent_view: "WeeklyAssignmentsView", default_old: str, default_new: str):
        super().__init__()
        self.bot = bot
        self.parent_view = parent_view
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
        await interaction.response.defer(ephemeral=True)

        count = await self.bot.db.process_weekly_rollover(old_w, new_w)
        embed = discord.Embed(
            title="🎉 Week Rolled Over Successfully!",
            description=(
                f"• **Finalized Week**: `{old_w}`\n"
                f"  *(Unfinished chores recorded as missed debt)*\n"
                f"• **Active New Week**: `{new_w}`\n"
                f"• **Assignments Provisioned**: **{count}** tasks"
            ),
            color=discord.Color.green(),
            timestamp=datetime.utcnow(),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        if self.parent_view:
            self.parent_view.week = new_w
            new_embed = await self.parent_view.build_assignments_embed()
            if interaction.message:
                await interaction.message.edit(embed=new_embed, view=self.parent_view)


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

        first = self.user_data.get("first_name", "")
        last = self.user_data.get("last_name", "")
        name = f"{first} {last}".strip()
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


class WeeklyAssignmentsView(discord.ui.View):
    """Interactive manager dashboard to view, reassign, force approve, or delete weekly chores."""

    def __init__(self, bot: commands.Bot, week: str | None = None):
        super().__init__(timeout=None)
        self.bot = bot
        self.week = week or get_iso_week()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not check_is_manager(interaction.user, interaction.guild):
            await interaction.response.send_message(
                "⛔ **Restricted**: Only members with the **Manager** role can modify chore assignments.",
                ephemeral=True,
            )
            return False
        return True

    def _get_current_week(self) -> str:
        return self.week or get_iso_week()

    async def build_assignments_embed(self) -> discord.Embed:
        week = self._get_current_week()
        rows = await self.bot.db.get_weekly_assignments_detailed(week)

        embed = discord.Embed(
            title=f"📋 House Chore Assignments — Week `{week}`",
            description="Manage active chore assignments for each housemate.\n"
                        "Use the buttons below to reassign, force-approve, add tasks, or remove assignments.",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow(),
        )

        if not rows:
            embed.description = f"```\nNo chore assignments found for week {week}. Use 'Assign Task' or weekly rollover.\n```"
            return embed

        status_emojis = {
            "approved": "✅ APPROVED",
            "under_review": "⏳ REVIEW",
            "pending": "▫️ PENDING",
            "rejected": "❌ REDO",
            "missed": "⚠️ MISSED",
        }

        # Group assignments by housemate
        member_map: dict[str, list[str]] = {}
        for r in rows:
            member_name = f"{r['first_name']} {r['last_name']}"
            stat = status_emojis.get(r['status'], r['status'].upper())
            day_text = f"Due: {format_due_day(r['due_day'])}"
            item_line = f"• **{r['title']}** (`{r['hours']}h`) — `{stat}` ({day_text})"
            member_map.setdefault(member_name, []).append(item_line)

        for member, chore_lines in member_map.items():
            embed.add_field(
                name=f"👤 {member}",
                value="\n".join(chore_lines),
                inline=False,
            )

        embed.set_footer(text=f"Total active assignments: {len(rows)} • Managers only")
        return embed

    @discord.ui.button(
        label="Reassign Chore",
        style=discord.ButtonStyle.primary,
        emoji="✏️",
        custom_id="weekly_mgr_reassign",
        row=0,
    )
    async def reassign_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        week = self._get_current_week()
        rows = await self.bot.db.get_weekly_assignments_detailed(week)
        if not rows:
            await interaction.response.send_message("❌ No assignments to reassign.", ephemeral=True)
            return

        options = [
            discord.SelectOption(
                label=f"{r['first_name']}: {r['title'][:25]}",
                value=f"{r['cid']}:{r['uid']}",
                description=f"{r['hours']}h • Status: {r['status']}",
            )
            for r in rows[:25]
        ]

        step1_view = discord.ui.View(timeout=60)
        select_assign = discord.ui.Select(
            placeholder="Step 1: Select the assignment to move...",
            options=options,
        )

        async def assignment_picked(s1_inter: discord.Interaction):
            cid_str, old_uid_str = select_assign.values[0].split(":")
            cid = int(cid_str)
            old_uid = int(old_uid_str)
            chore = await self.bot.db.get_chore(cid)

            step2_view = discord.ui.View(timeout=60)
            user_select = discord.ui.UserSelect(
                placeholder="Step 2: Pick the new housemate to receive this chore...",
                min_values=1,
                max_values=1,
            )

            async def new_user_picked(s2_inter: discord.Interaction):
                new_member = user_select.values[0]

                # Ensure new user is registered
                db_user = await self.bot.db.get_user(new_member.id)
                if not db_user:
                    parts = new_member.display_name.split()
                    f_name = parts[0] if parts else new_member.name
                    l_name = " ".join(parts[1:]) if len(parts) > 1 else ""
                    await self.bot.db.upsert_user(new_member.id, f_name, l_name, 0)

                await self.bot.db.reassign_chore(old_uid, new_member.id, cid, week)
                await s2_inter.response.edit_message(
                    content=f"✅ Reassigned **{chore['title']}** to {new_member.mention} for week `{week}`!",
                    view=None,
                )
                new_embed = await self.build_assignments_embed()
                if interaction.message:
                    await interaction.message.edit(embed=new_embed, view=self)

            user_select.callback = new_user_picked
            step2_view.add_item(user_select)

            await s1_inter.response.edit_message(
                content=f"Reassigning **{chore['title']}** ({chore['hours']}h). Who should get this chore?",
                view=step2_view,
            )

        select_assign.callback = assignment_picked
        step1_view.add_item(select_assign)

        await interaction.response.send_message(
            "Select which housemate's assignment you want to change:",
            view=step1_view,
            ephemeral=True,
        )

    @discord.ui.button(
        label="Set Status / Approve",
        style=discord.ButtonStyle.success,
        emoji="⚙️",
        custom_id="weekly_mgr_status",
        row=0,
    )
    async def edit_status_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        week = self._get_current_week()
        rows = await self.bot.db.get_weekly_assignments_detailed(week)
        if not rows:
            await interaction.response.send_message("❌ No assignments found.", ephemeral=True)
            return

        options = [
            discord.SelectOption(
                label=f"{r['first_name']}: {r['title'][:25]}",
                value=f"{r['cid']}:{r['uid']}",
                description=f"Current: {r['status']}",
            )
            for r in rows[:25]
        ]

        step1_view = discord.ui.View(timeout=60)
        select_assign = discord.ui.Select(
            placeholder="Select assignment to change status...",
            options=options,
        )

        async def assignment_picked(s1_inter: discord.Interaction):
            cid_str, uid_str = select_assign.values[0].split(":")
            cid = int(cid_str)
            uid = int(uid_str)
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
                new_embed = await self.build_assignments_embed()
                if interaction.message:
                    await interaction.message.edit(embed=new_embed, view=self)

            status_select.callback = status_picked
            status_view.add_item(status_select)

            await s1_inter.response.edit_message(
                content=f"Change status for **{chore['title']}**:",
                view=status_view,
            )

        select_assign.callback = assignment_picked
        step1_view.add_item(select_assign)

        await interaction.response.send_message(
            "Select an assignment to change status:",
            view=step1_view,
            ephemeral=True,
        )

    @discord.ui.button(
        label="Assign Task",
        style=discord.ButtonStyle.secondary,
        emoji="➕",
        custom_id="weekly_mgr_add_task",
        row=0,
    )
    async def add_task_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        chores = await self.bot.db.get_all_chores()
        if not chores:
            await interaction.response.send_message("❌ No master chores available.", ephemeral=True)
            return

        options = [
            discord.SelectOption(
                label=f"#{c['cid']} {c['title'][:40]}",
                value=str(c["cid"]),
                description=f"{c['hours']}h credit • Due: {format_due_day(c['due_day'])}",
            )
            for c in chores[:25]
        ]

        step1_view = discord.ui.View(timeout=60)
        chore_select = discord.ui.Select(
            placeholder="Step 1: Pick chore to assign...",
            options=options,
        )

        async def chore_picked(s1_inter: discord.Interaction):
            cid = int(chore_select.values[0])
            chore = await self.bot.db.get_chore(cid)
            week = self._get_current_week()

            step2_view = discord.ui.View(timeout=60)
            user_select = discord.ui.UserSelect(
                placeholder="Step 2: Pick housemate to receive chore...",
                min_values=1,
                max_values=1,
            )

            async def user_picked(s2_inter: discord.Interaction):
                target_user = user_select.values[0]
                db_user = await self.bot.db.get_user(target_user.id)
                if not db_user:
                    parts = target_user.display_name.split()
                    f_name = parts[0] if parts else target_user.name
                    l_name = " ".join(parts[1:]) if len(parts) > 1 else ""
                    await self.bot.db.upsert_user(target_user.id, f_name, l_name, 0)

                await self.bot.db.assign_chore(cid, target_user.id, week)
                await self.bot.db.add_chore_template(cid, target_user.id)
                await s2_inter.response.edit_message(
                    content=f"✅ Assigned **{chore['title']}** to {target_user.mention} for week `{week}`!",
                    view=None,
                )
                new_embed = await self.build_assignments_embed()
                if interaction.message:
                    await interaction.message.edit(embed=new_embed, view=self)

            user_select.callback = user_picked
            step2_view.add_item(user_select)

            await s1_inter.response.edit_message(
                content=f"Assigning **{chore['title']}** ({chore['hours']}h). Who gets this chore?",
                view=step2_view,
            )

        chore_select.callback = chore_picked
        step1_view.add_item(chore_select)

        await interaction.response.send_message(
            "Assign a chore for this week:",
            view=step1_view,
            ephemeral=True,
        )

    @discord.ui.button(
        label="Remove Assignment",
        style=discord.ButtonStyle.danger,
        emoji="🗑️",
        custom_id="weekly_mgr_remove_task",
        row=0,
    )
    async def remove_task_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        week = self._get_current_week()
        rows = await self.bot.db.get_weekly_assignments_detailed(week)
        if not rows:
            await interaction.response.send_message("❌ No assignments to remove.", ephemeral=True)
            return

        options = [
            discord.SelectOption(
                label=f"{r['first_name']}: {r['title'][:25]}",
                value=f"{r['cid']}:{r['uid']}",
                description=f"Remove from week {week}",
            )
            for r in rows[:25]
        ]

        select_view = discord.ui.View(timeout=60)
        remove_select = discord.ui.Select(
            placeholder="Select assignment to remove from this week...",
            options=options,
        )

        async def remove_picked(s_inter: discord.Interaction):
            cid_str, uid_str = remove_select.values[0].split(":")
            cid = int(cid_str)
            uid = int(uid_str)
            chore = await self.bot.db.get_chore(cid)

            await self.bot.db.delete_assignment(cid, uid, week)
            await s_inter.response.edit_message(
                content=f"🗑️ Removed assignment **{chore['title']}** from <@{uid}> for week `{week}`.",
                view=None,
            )
            new_embed = await self.build_assignments_embed()
            if interaction.message:
                await interaction.message.edit(embed=new_embed, view=self)

        remove_select.callback = remove_picked
        select_view.add_item(remove_select)

        await interaction.response.send_message(
            "Select an assignment to remove:",
            view=select_view,
            ephemeral=True,
        )

    @discord.ui.button(
        label="Makeup Bounties",
        style=discord.ButtonStyle.secondary,
        emoji="🧹",
        custom_id="weekly_mgr_makeups",
        row=0,
    )
    async def makeups_dashboard_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not check_is_manager(interaction.user, interaction.guild):
            await interaction.response.send_message(
                "⛔ **Restricted**: Only members with the **Manager** role can open makeup bounties.",
                ephemeral=True,
            )
            return

        from lutherbot.cogs.makeups import MakeupDashboardView
        current_w = self._get_current_week()
        view = MakeupDashboardView(self.bot, week=current_w)
        embed = await view.build_dashboard_embed()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(
        label="Roll Over Week",
        style=discord.ButtonStyle.danger,
        emoji="⏩",
        custom_id="weekly_mgr_rollover",
        row=1,
    )
    async def rollover_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        current_week = self._get_current_week()
        next_week = get_next_week(current_week)
        prev_week = get_prev_week(current_week)

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

        async def confirm_current_to_next(c_inter: discord.Interaction):
            await c_inter.response.defer(ephemeral=True)
            count = await self.bot.db.process_weekly_rollover(current_week, next_week)
            self.week = next_week  # Advance view's active week
            result_embed = discord.Embed(
                title="🎉 Week Rolled Over Successfully!",
                description=(
                    f"• **Finalized Week**: `{current_week}` (uncompleted chores recorded as missed debt)\n"
                    f"• **Active New Week**: `{next_week}`\n"
                    f"• **Assignments Provisioned**: **{count}** tasks"
                ),
                color=discord.Color.green(),
                timestamp=datetime.utcnow(),
            )
            await c_inter.followup.send(embed=result_embed, ephemeral=True)
            new_embed = await self.build_assignments_embed()
            if interaction.message:
                await interaction.message.edit(embed=new_embed, view=self)

        btn_curr.callback = confirm_current_to_next
        confirm_view.add_item(btn_curr)

        if missing_prev:
            btn_prev = discord.ui.Button(
                label=f"Roll {prev_week} ➔ {current_week}",
                style=discord.ButtonStyle.primary,
                emoji="⏮️",
            )

            async def confirm_prev_to_current(p_inter: discord.Interaction):
                await p_inter.response.defer(ephemeral=True)
                count = await self.bot.db.process_weekly_rollover(prev_week, current_week)
                self.week = current_week
                result_embed = discord.Embed(
                    title="🎉 Previous Week Finalized!",
                    description=(
                        f"• **Finalized Week**: `{prev_week}`\n"
                        f"• **Current Week**: `{current_week}`\n"
                        f"• **Assignments Provisioned**: **{count}** tasks"
                    ),
                    color=discord.Color.green(),
                    timestamp=datetime.utcnow(),
                )
                await p_inter.followup.send(embed=result_embed, ephemeral=True)
                new_embed = await self.build_assignments_embed()
                if interaction.message:
                    await interaction.message.edit(embed=new_embed, view=self)

            btn_prev.callback = confirm_prev_to_current
            confirm_view.add_item(btn_prev)

        btn_custom = discord.ui.Button(
            label="Custom Weeks...",
            style=discord.ButtonStyle.secondary,
            emoji="⚙️",
        )

        async def custom_weeks_clicked(cust_inter: discord.Interaction):
            modal = CustomRolloverModal(self.bot, self, current_week, next_week)
            await cust_inter.response.send_modal(modal)

        btn_custom.callback = custom_weeks_clicked
        confirm_view.add_item(btn_custom)

        await interaction.response.send_message(
            embed=confirm_embed,
            view=confirm_view,
            ephemeral=True,
        )

    @discord.ui.button(
        label="Pending Reviews",
        style=discord.ButtonStyle.secondary,
        emoji="📬",
        custom_id="weekly_mgr_pending_threads",
        row=1,
    )
    async def pending_threads_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await self._show_pending_reviews(interaction)

    @discord.ui.button(
        label="Edit Debt Hours",
        style=discord.ButtonStyle.secondary,
        emoji="⏱️",
        custom_id="weekly_mgr_edit_hours",
        row=1,
    )
    async def edit_hours_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
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
            for u in users[:25]
        ]

        pick_view = discord.ui.View(timeout=60)
        user_select = discord.ui.Select(
            placeholder="Select housemate to edit debt hours...",
            options=options,
        )

        async def user_selected(s_inter: discord.Interaction):
            selected_uid = int(user_select.values[0])
            user_data = await self.bot.db.get_user(selected_uid)
            modal = EditDebtModal(self.bot, selected_uid, dict(user_data))
            await s_inter.response.send_modal(modal)

        user_select.callback = user_selected
        pick_view.add_item(user_select)

        await interaction.response.send_message(
            "Select which housemate's missed hours debt you want to adjust:",
            view=pick_view,
            ephemeral=True,
        )

    @discord.ui.button(
        label="Refresh",
        style=discord.ButtonStyle.secondary,
        emoji="🔄",
        custom_id="weekly_mgr_refresh",
        row=1,
    )
    async def refresh_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        new_embed = await self.build_assignments_embed()
        await interaction.response.edit_message(embed=new_embed, view=self)

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
            description=f"There are **{len(rows)}** submission thread(s) waiting for manager review.\n"
                        "Click the thread links or use the menu below to jump directly to any thread:",
            color=discord.Color.gold(),
            timestamp=datetime.utcnow(),
        )

        options = []
        for i, r in enumerate(rows[:25]):
            type_label = "Bounty" if r["chore_type"] == "makeup" else "Chore"
            thread_mention = f"<#{r['thread_id']}>"
            status_text = r["status"].replace("_", " ").upper()
            embed.add_field(
                name=f"{i+1}. {r['first_name']} {r['last_name']} — {r['title']} ({r['hours']}h)",
                value=f"Type: `{type_label}` | Week: `{r['week']}` | Status: `{status_text}`\nThread: {thread_mention}",
                inline=False,
            )
            options.append(
                discord.SelectOption(
                    label=f"{r['first_name']}: {r['title'][:25]}",
                    value=str(r["thread_id"]),
                    description=f"{type_label} • {r['hours']}h • Week {r['week']}",
                )
            )

        view = discord.ui.View(timeout=120)
        select = discord.ui.Select(
            placeholder="Select a review thread to jump to...",
            options=options,
        )

        async def select_thread(s_inter: discord.Interaction):
            thread_id = int(select.values[0])
            thread = interaction.guild.get_thread(thread_id) if interaction.guild else None
            jump_url = thread.jump_url if thread else f"https://discord.com/channels/{interaction.guild_id}/{thread_id}"
            jump_view = discord.ui.View()
            jump_view.add_item(
                discord.ui.Button(
                    label="Jump to Review Thread",
                    url=jump_url,
                    style=discord.ButtonStyle.link,
                    emoji="🔗",
                )
            )
            await s_inter.response.send_message(
                f"🔗 Direct link to review thread <#{thread_id}>:",
                view=jump_view,
                ephemeral=True,
            )

        select.callback = select_thread
        view.add_item(select)

        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
