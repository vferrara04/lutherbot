# src/lutherbot/cogs/chores.py
from datetime import datetime
import discord
from discord import app_commands
from discord.ext import commands

from lutherbot.cogs.helpers import (
    has_manager_role,
    format_due_day,
    parse_due_day,
    get_iso_week,
    get_next_week,
    send_or_edit,
    make_jump_view,
    ensure_user_registered,
    chore_autocomplete,
    post_dashboard_to_channel,
    PaginatedSelectView,
)
from lutherbot.cogs.reviews import ThreadReviewView, spawn_review_thread
from lutherbot.cogs.modals import EditChoreModal
from lutherbot.cogs.chore_views import PartnerPromptView, ChoreManagerView
from lutherbot.cogs.assignments import WeeklyAssignmentsView
from lutherbot import config


class ChoresCog(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _get_current_week(self) -> str:
        return get_iso_week()

    # --- Manager Dashboards ---

    @app_commands.command(
        name="chore_manager",
        description="Manager: Master chore templates definition dashboard",
    )
    @has_manager_role()
    async def chore_manager(self, interaction: discord.Interaction):
        view = ChoreManagerView(self.bot)
        embed = await view.build_manager_embed()
        await post_dashboard_to_channel(
            interaction,
            config.WORM_CHANNEL_ID,
            view,
            embed,
            "✅ Master chore templates dashboard posted!",
        )

    @app_commands.command(
        name="assignments_dashboard",
        description="Manager: View and edit active weekly chore assignments for all members",
    )
    @has_manager_role()
    async def assignments_dashboard(self, interaction: discord.Interaction):
        view = WeeklyAssignmentsView(self.bot)
        embed = await view.build_assignments_embed()
        await post_dashboard_to_channel(
            interaction,
            config.WORM_CHANNEL_ID,
            view,
            embed,
            "✅ Weekly chore assignments dashboard posted!",
        )

    @app_commands.command(
        name="week_rollover",
        description="Manager: Advance chore week, finalize missed debt & provision next week",
    )
    @app_commands.describe(
        old_week="The departing week (default: current week, e.g. 2026-W41)",
        new_week="The target week to provision (default: next week, e.g. 2026-W42)",
    )
    @has_manager_role()
    async def week_rollover(
        self,
        interaction: discord.Interaction,
        old_week: str = "",
        new_week: str = "",
    ):
        src_w = old_week.strip().upper() if old_week else self._get_current_week()
        tgt_w = new_week.strip().upper() if new_week else get_next_week(src_w)

        await interaction.response.defer(ephemeral=True)
        count = await self.bot.db.process_weekly_rollover(src_w, tgt_w)
        embed = discord.Embed(
            title="🎉 Week Rolled Over Successfully!",
            description=(
                f"• **Finalized Week**: `{src_w}`\n"
                f"  *(Uncompleted chores recorded as delinquent missed debt)*\n"
                f"• **Active New Week**: `{tgt_w}`\n"
                f"• **New Assignments Provisioned**: **{count}** tasks"
            ),
            color=discord.Color.green(),
            timestamp=datetime.utcnow(),
        )
        await interaction.followup.send(embed=embed)

    @app_commands.command(
        name="pending_reviews",
        description="Manager: View all active chore submission threads awaiting review",
    )
    @has_manager_role()
    async def pending_reviews(self, interaction: discord.Interaction):
        view = WeeklyAssignmentsView(self.bot)
        await view._show_pending_reviews(interaction)

    # --- Direct Manager Commands ---

    @app_commands.command(
        name="chore_add",
        description="Manager: Add a master chore template",
    )
    @app_commands.describe(
        title="Title of the chore",
        description="Checklist instructions",
        hours="Credit hours granted",
        due_day="Due day (Sunday, Monday, Tuesday...)",
    )
    @has_manager_role()
    async def chore_add(
        self,
        interaction: discord.Interaction,
        title: str,
        description: str = "",
        hours: int = 1,
        due_day: str = "",
    ):
        day_int = parse_due_day(due_day) if due_day else None
        cid = await self.bot.db.add_chore(
            title=title.strip(),
            description=description.strip(),
            hours=max(1, hours),
            due_day=day_int,
        )
        await interaction.response.send_message(
            f"✅ Created Chore **#{cid}**: `{title}` ({hours}h credit, Due: **{format_due_day(day_int)}**)!",
            ephemeral=True,
        )

    @app_commands.command(
        name="chore_edit",
        description="Manager: Interactively edit an existing chore template",
    )
    @app_commands.describe(chore_id="The chore to edit")
    @app_commands.autocomplete(chore_id=chore_autocomplete)
    @has_manager_role()
    async def chore_edit(self, interaction: discord.Interaction, chore_id: int):
        chore = await self.bot.db.get_chore(chore_id)
        if not chore:
            await interaction.response.send_message(f"❌ Chore template `#{chore_id}` not found.", ephemeral=True)
            return
        await interaction.response.send_modal(EditChoreModal(self.bot, dict(chore)))

    @app_commands.command(
        name="chore_delete",
        description="Manager: Delete a master chore template",
    )
    @app_commands.describe(chore_id="The chore to delete")
    @app_commands.autocomplete(chore_id=chore_autocomplete)
    @has_manager_role()
    async def chore_delete(self, interaction: discord.Interaction, chore_id: int):
        chore = await self.bot.db.get_chore(chore_id)
        if not chore:
            await interaction.response.send_message(f"❌ Chore template `#{chore_id}` not found.", ephemeral=True)
            return

        await self.bot.db.delete_chore(chore_id)
        await interaction.response.send_message(
            f"🗑️ Deleted master chore **#{chore_id}** (`{chore['title']}`).",
            ephemeral=True,
        )

    @app_commands.command(
        name="chore_assign",
        description="Manager: Assign a chore to a housemate",
    )
    @app_commands.describe(
        chore_id="Chore to assign",
        member="Housemate to assign chore to",
        week="Target week identifier (e.g. 2026-W41, default current)",
        recurring="Save to recurring weekly template (default: True)",
    )
    @app_commands.autocomplete(chore_id=chore_autocomplete)
    @has_manager_role()
    async def chore_assign(
        self,
        interaction: discord.Interaction,
        chore_id: int,
        member: discord.Member,
        week: str = "",
        recurring: bool = True,
    ):
        chore = await self.bot.db.get_chore(chore_id)
        if not chore:
            await interaction.response.send_message(f"❌ Chore `#{chore_id}` does not exist.", ephemeral=True)
            return

        target_week = week if week else self._get_current_week()
        await ensure_user_registered(self.bot.db, member)
        await self.bot.db.assign_chore(chore_id, member.id, target_week)
        if recurring:
            await self.bot.db.add_chore_template(chore_id, member.id)

        rec_str = " (Saved to recurring templates)" if recurring else ""
        await interaction.response.send_message(
            f"✅ Assigned **{chore['title']}** to {member.mention} for week `{target_week}`!{rec_str}",
            ephemeral=True,
        )

    # --- Public Member Commands ---

    @app_commands.command(
        name="chore_submit",
        description="Submit proof for your assigned chore or claimed makeup bounty",
    )
    async def submit_chores(self, interaction: discord.Interaction):
        week = self._get_current_week()
        user_chores = await self.bot.db.get_user_chores(interaction.user.id, week)
        claimed_makeups = await self.bot.db.get_user_claimed_makeups(interaction.user.id)

        total_items = len(user_chores) + len(claimed_makeups)
        if total_items == 0:
            await interaction.response.send_message(
                "⚠️ You have no pending assigned chores or claimed makeup bounties to submit proof for!",
                ephemeral=True,
            )
            return

        if total_items == 1:
            if user_chores:
                await self._handle_submission_flow(interaction, user_chores[0], week)
            else:
                await self._handle_makeup_submission_flow(interaction, claimed_makeups[0])
            return

        options = [
            discord.SelectOption(
                label=f"📋 [Assigned] #{c['chore_id']} {c['title'][:32]}",
                value=f"regular_{c['chore_id']}",
                description=f"{c['hours']}h assigned task • Status: {c['status']}",
            )
            for c in user_chores
        ] + [
            discord.SelectOption(
                label=f"🧹 [Makeup] #{m['mid']} {m['title'][:32]}",
                value=f"makeup_{m['mid']}",
                description=f"{m['hours']}h bounty credit • Week: {m['week']}",
            )
            for m in claimed_makeups
        ]

        async def task_picked(s_inter: discord.Interaction, val: str):
            if val.startswith("regular_"):
                selected_cid = int(val.replace("regular_", ""))
                target_chore = next(c for c in user_chores if c["chore_id"] == selected_cid)
                await self._handle_submission_flow(s_inter, target_chore, week)
            elif val.startswith("makeup_"):
                selected_mid = int(val.replace("makeup_", ""))
                target_makeup = next(m for m in claimed_makeups if m["mid"] == selected_mid)
                await self._handle_makeup_submission_flow(s_inter, target_makeup)

        await interaction.response.send_message(
            "Select which assigned chore or claimed makeup bounty you are submitting proof for:",
            view=PaginatedSelectView(options, "Choose task to submit proof for...", task_picked),
            ephemeral=True,
        )

    async def _send_existing_thread_link(self, interaction: discord.Interaction, thread_id: int, label_prefix: str):
        thread = interaction.guild.get_thread(thread_id) if interaction.guild else None
        jump_url = thread.jump_url if thread else f"https://discord.com/channels/{interaction.guild_id}/{thread_id}"
        await send_or_edit(
            interaction,
            f"📋 **Your thread is already open for {label_prefix}!** Click below to jump straight to it:",
            view=make_jump_view("Jump to Your Ticket Thread", jump_url),
        )

    async def _handle_submission_flow(self, interaction: discord.Interaction, chore: dict, week: str):
        if chore["thread_id"]:
            await self._send_existing_thread_link(
                interaction, chore["thread_id"], f"#{chore['chore_id']} {chore['title']}"
            )
            return

        partners = await self.bot.db.get_chore_partners(
            chore_id=chore["chore_id"],
            week=week,
            user_id=interaction.user.id,
        )

        prompt = PartnerPromptView(self.bot, interaction.user.id, chore, partners, week)
        if not partners:
            await prompt._spawn_thread(interaction, [interaction.user.id], is_shared=False)
        else:
            partner_names = ", ".join(f"**{p['first_name']} {p['last_name']}**" for p in partners)
            await send_or_edit(
                interaction,
                f"🤝 You share **{chore['title']}** with {partner_names}.\n"
                "Are you submitting proof for just yourself, or for both of you?",
                view=prompt,
            )

    async def _handle_makeup_submission_flow(self, interaction: discord.Interaction, task: dict):
        if task["thread_id"]:
            await self._send_existing_thread_link(
                interaction, task["thread_id"], f"Makeup #{task['mid']} {task['title']}"
            )
            return

        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)

        thread_name = f"Makeup #{task['mid']} - {interaction.user.display_name}"
        embed = discord.Embed(
            title=f"🧹 Makeup Review: {task['title']}",
            description=(
                f"**Claimed By:** {interaction.user.mention}\n"
                f"**Debt Credit:** `{task['hours']} hrs`\n"
                f"**Target Week:** `{task['week']}`\n\n"
                "📸 **Please drop all photo proof directly into this thread.**\n"
                "Managers will review and approve using the buttons below."
            ),
            color=discord.Color.gold(),
        )

        thread, err = await spawn_review_thread(
            interaction=interaction,
            thread_title=thread_name,
            content=f"👋 {interaction.user.mention}",
            embed=embed,
            view=ThreadReviewView(),
        )

        if not thread:
            await send_or_edit(interaction, f"❌ **Could not create makeup submission ticket**:\n{err}")
            return

        await self.bot.db.link_makeup_thread(task["mid"], thread.id)
        await send_or_edit(
            interaction,
            "✅ Makeup bounty ticket created! Click below to upload your photo proof:",
            view=make_jump_view(f"Jump to #{thread.name}", thread.jump_url, emoji="🚀"),
        )

    @app_commands.command(
        name="my_chores",
        description="View your active assignments and missed hours",
    )
    async def my_chores(self, interaction: discord.Interaction):
        week_str = self._get_current_week()
        user = await self.bot.db.get_user(interaction.user.id)
        chores = await self.bot.db.get_user_chores(interaction.user.id, week_str)
        debt = user["missed_chore_hours"] if user else 0

        embed = discord.Embed(
            title=f"📋 Your Chores — Week {week_str}",
            color=discord.Color.blue(),
        )
        embed.add_field(
            name="Debt Hours",
            value=f"`{debt} hrs` missed" if debt > 0 else "✅ No Missed Chores",
            inline=False,
        )

        if not chores:
            embed.add_field(name="Assigned Tasks", value="No open chores this week!", inline=False)
        else:
            for c in chores[:24]:
                status_val = c["status"].upper() if "status" in c.keys() else "PENDING"
                embed.add_field(
                    name=f"#{c['chore_id']} {c['title']} ({c['hours']}h)",
                    value=f"Status: `{status_val}`",
                    inline=False,
                )
            if len(chores) > 24:
                embed.set_footer(text=f"Showing 24 of {len(chores)} assigned chores.")

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ChoresCog(bot))