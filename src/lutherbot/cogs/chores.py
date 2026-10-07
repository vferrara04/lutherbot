# src/lutherbot/cogs/chores.py
from datetime import datetime
import discord
from discord import app_commands
from discord.ext import commands
from lutherbot import config


# =============================================================================
# 1. Thread Review View (Persistent inside submission threads)
# =============================================================================


class ThreadReviewView(discord.ui.View):
    """Attached to submission threads.

    timeout=None allows buttons to work even after bot restarts.
    """

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Approve",
        style=discord.ButtonStyle.success,
        emoji="✅",
        custom_id="chore_review_approve",
    )
    async def approve(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        thread = interaction.channel
        db = interaction.client.db

        # Fetch records tied to this thread
        assignments = await db.get_assignment_by_thread(thread.id)
        if not assignments:
            await interaction.response.send_message(
                "❌ No active assignment linked to this thread.", ephemeral=True
            )
            return

        # 1. Update SQLite
        await db.update_status_by_thread(thread.id, "approved")

        # 2. Check if any assignment was a makeup chore; if so, resolve debt
        for row in assignments:
            if row["chore_type"] == "makeup":
                await db.resolve_missed_chores(row["mid"], row["uid"])

        # 3. Freeze buttons on the review card
        for child in self.children:
            child.disabled = True

        embed = interaction.message.embeds[0]
        embed.color = discord.Color.green()
        embed.title = "✅ Approved"
        embed.set_footer(
            text=f"Approved by {interaction.user.display_name} • {datetime.now().strftime('%b %d, %H:%M')}"
        )

        await interaction.response.edit_message(embed=embed, view=self)
        await thread.send(
            "🎉 **Submission approved!** Archiving and locking ticket..."
        )

        # 4. Lock and archive the thread
        await thread.edit(locked=True, archived=True)

    @discord.ui.button(
        label="Reject",
        style=discord.ButtonStyle.danger,
        emoji="❌",
        custom_id="chore_review_reject",
    )
    async def reject(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        thread = interaction.channel
        db = interaction.client.db

        assignments = await db.get_assignment_by_thread(thread.id)
        if not assignments:
            await interaction.response.send_message(
                "❌ No assignment found.", ephemeral=True
            )
            return

        # Update status back to rejected
        await db.update_status_by_thread(thread.id, "rejected")

        # Disable buttons so manager must re-review upon new photo
        for child in self.children:
            child.disabled = True

        embed = interaction.message.embeds[0]
        embed.color = discord.Color.red()
        embed.title = "❌ Rejected - Changes Required"
        embed.set_footer(
            text=f"Rejected by {interaction.user.display_name} • {datetime.now().strftime('%b %d, %H:%M')}"
        )

        await interaction.response.edit_message(embed=embed, view=self)

        mentions = " ".join(f"<@{row['uid']}>" for row in assignments)
        await thread.send(
            f"⚠️ {mentions} Your proof was rejected. Please review manager feedback, redo the task, and upload new photos here."
        )


# =============================================================================
# 2. Partner Prompt View (Ephemeral choice for shared chores)
# =============================================================================


class PartnerPromptView(discord.ui.View):

    def __init__(
        self,
        bot: commands.Bot,
        user_id: int,
        chore: dict,
        partners: list,
        week: str,
    ):
        super().__init__(timeout=60)
        self.bot = bot
        self.user_id = user_id
        self.chore = chore
        self.partners = partners
        self.week = week

    async def _spawn_thread(
        self,
        interaction: discord.Interaction,
        target_uids: list[int],
        is_shared: bool,
    ):
        submissions_channel = interaction.guild.get_channel(
            config.SUBMISSION_CHANNEL_ID
        )
        if not submissions_channel:
            await interaction.response.edit_message(
                content="❌ Submissions channel not configured.", view=None
            )
            return

        # 1. Format thread title
        partner_names = " & Partner" if is_shared else ""
        thread_title = f"Chore #{self.chore['chore_id']} - {interaction.user.display_name}{partner_names}"

        # 2. Spawn Discord Thread
        thread = await submissions_channel.create_thread(
            name=thread_title[:100],
            auto_archive_duration=1440,
            type=discord.ChannelType.public_thread,
        )

        # 3. Link assignments in database
        await self.bot.db.link_thread(
            chore_id=self.chore["chore_id"],
            user_ids=target_uids,
            week=self.week,
            thread_id=thread.id,
        )

        # 4. Post review card in thread
        mentions = " ".join(f"<@{uid}>" for uid in target_uids)
        embed = discord.Embed(
            title=f"📋 Submission: {self.chore['title']}",
            description=(
                f"**Assigned:** {mentions}\n"
                f"**Hours:** `{self.chore['hours']}h`\n\n"
                "📸 **Please drop all photo proof directly into this thread.**\n"
                "Managers will review and approve using the buttons below."
            ),
            color=discord.Color.blue(),
        )

        await thread.send(
            content=f"👋 {mentions}", embed=embed, view=ThreadReviewView()
        )

        # 5. Acknowledge the user
        await interaction.response.edit_message(
            content=f"✅ Submission ticket created: [Jump to #{thread.name}]({thread.jump_url})",
            view=None,
        )

    @discord.ui.button(
        label="Just Myself",
        style=discord.ButtonStyle.secondary,
        emoji="👤",
    )
    async def just_me(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await self._spawn_thread(
            interaction, target_uids=[self.user_id], is_shared=False
        )

    @discord.ui.button(
        label="Both of Us",
        style=discord.ButtonStyle.primary,
        emoji="👥",
    )
    async def both_of_us(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        target_uids = [self.user_id] + [p["uid"] for p in self.partners]
        await self._spawn_thread(
            interaction, target_uids=target_uids, is_shared=True
        )


# =============================================================================
# 3. Interactive Spreadsheet Dashboard View
# =============================================================================


class ChoreDashboardView(discord.ui.View):
    """The persistent interactive dashboard.

    Renders a live monospace table and handles submission / claiming actions.
    """

    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    def _get_current_week(self) -> str:
        year, week, _ = datetime.now().isocalendar()
        return f"{year}-W{week:02d}"

    async def build_spreadsheet_embed(self, guild_id: int) -> discord.Embed:
        """Generates an ASCII grid resembling a live spreadsheet."""
        week = self._get_current_week()

        # Query all assignments for the current week
        query = """
            SELECT u.first_name, c.title, c.hours, ca.status
            FROM chore_assignments ca
            JOIN users u ON ca.uid = u.uid
            JOIN chores c ON ca.cid = c.cid
            WHERE ca.week = ?
            ORDER BY ca.status DESC, u.first_name ASC;
        """
        async with self.bot.db.conn.execute(query, (week,)) as cursor:
            rows = await cursor.fetchall()

        embed = discord.Embed(
            title=f"📊 Chore Status Sheet — Week `{week}`",
            color=discord.Color.dark_theme(),
            timestamp=datetime.utcnow(),
        )

        if not rows:
            embed.description = "```\nNo active chore assignments found for this week.\n```"
            return embed

        # Format as fixed-width spreadsheet columns
        # Header: Member (10) | Chore (16) | Hrs (3) | Status (10)
        lines = [
            f"{'Member':<10} | {'Chore':<16} | {'Hrs':<3} | {'Status':<10}",
            "-" * 47,
        ]

        status_icons = {
            "approved": "DONE",
            "under_review": "REVIEW",
            "pending": "PENDING",
            "rejected": "REDO",
            "missed": "MISSED",
        }

        for r in rows:
            name = (
                r["first_name"][:9]
                if len(r["first_name"]) > 9
                else r["first_name"]
            )
            title = r["title"][:15] if len(r["title"]) > 15 else r["title"]
            hrs = str(r["hours"])
            stat = status_icons.get(r["status"], r["status"].upper())
            lines.append(f"{name:<10} | {title:<16} | {hrs:<3} | {stat:<10}")

        table_text = "\n".join(lines)
        embed.description = (
            f"```text\n{table_text}\n```\n"
            "*Click buttons below to submit photo proof, claim makeup chores, or refresh the sheet.*"
        )
        embed.set_footer(text="Auto-refreshes on user actions")
        return embed

    @discord.ui.button(
        label="Submit Proof",
        style=discord.ButtonStyle.primary,
        emoji="📸",
        custom_id="dashboard_btn_submit",
    )
    async def submit_proof_click(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        week = self._get_current_week()

        # 1. Check user chores
        user_chores = await self.bot.db.get_user_chores(
            interaction.user.id, week
        )
        if not user_chores:
            await interaction.response.send_message(
                "⚠️ You have no pending or active chores for this week!",
                ephemeral=True,
            )
            return

        chore = user_chores[0]  # Grab primary active assignment

        # 2. Check if a thread is already running
        if chore["thread_id"]:
            thread_link = f"https://discord.com/channels/{interaction.guild_id}/{chore['thread_id']}"
            await interaction.response.send_message(
                f"⚠️ You already have an open ticket for this chore: [Open Thread]({thread_link})",
                ephemeral=True,
            )
            return

        # 3. Check for chore partners
        partners = await self.bot.db.get_chore_partners(
            chore_id=chore["chore_id"],
            week=week,
            user_id=interaction.user.id,
        )

        if not partners:
            # Solo task: open thread immediately
            prompt = PartnerPromptView(
                self.bot, interaction.user.id, chore, [], week
            )
            await prompt._spawn_thread(
                interaction, [interaction.user.id], is_shared=False
            )
        else:
            # Shared task: prompt whether to submit for partner too
            partner_names = ", ".join(
                f"**{p['first_name']} {p['last_name']}**" for p in partners
            )
            view = PartnerPromptView(
                self.bot, interaction.user.id, chore, partners, week
            )
            await interaction.response.send_message(
                f"🤝 You share **{chore['title']}** with {partner_names}.\n"
                "Are you submitting proof for just yourself, or for both of you?",
                view=view,
                ephemeral=True,
            )

    @discord.ui.button(
        label="Pickup Makeup",
        style=discord.ButtonStyle.secondary,
        emoji="🧹",
        custom_id="dashboard_btn_makeup",
    )
    async def pickup_makeup_click(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        # Check if user has missed debt hours
        user = await self.bot.db.get_user(interaction.user.id)
        if not user or user["missed_chore_hours"] <= 0:
            await interaction.response.send_message(
                "✨ You have 0 missed chore hours! No makeups needed.",
                ephemeral=True,
            )
            return

        available = await self.bot.db.get_available_makeups()
        if not available:
            await interaction.response.send_message(
                "📋 There are no available makeup chores posted right now.",
                ephemeral=True,
            )
            return

        # Create dropdown options for available makeups
        options = [
            discord.SelectOption(
                label=f"{m['title']} ({m['hours']} hrs)",
                value=str(m["mid"]),
                description=f"Makeup Task #{m['mid']}",
            )
            for m in available[:25]
        ]

        select_view = discord.ui.View(timeout=60)
        select_menu = discord.ui.Select(
            placeholder="Select a makeup chore to claim...", options=options
        )

        async def select_callback(select_inter: discord.Interaction):
            makeup_id = int(select_menu.values[0])
            claimed = await self.bot.db.claim_makeup(
                makeup_id, select_inter.user.id
            )
            if claimed:
                await select_inter.response.edit_message(
                    content=f"✅ You claimed **Makeup Chore #{makeup_id}**! Open a thread to submit proof when done.",
                    view=None,
                )
            else:
                await select_inter.response.edit_message(
                    content="❌ Someone else just claimed this chore! Try another.",
                    view=None,
                )

        select_menu.callback = select_callback
        select_view.add_item(select_menu)

        await interaction.response.send_message(
            f"Debt: `{user['missed_chore_hours']}h` missed. Choose a chore to work off:",
            view=select_view,
            ephemeral=True,
        )

    @discord.ui.button(
        label="Refresh",
        style=discord.ButtonStyle.secondary,
        emoji="🔄",
        custom_id="dashboard_btn_refresh",
    )
    async def refresh_sheet(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        # Re-query SQLite and update the message in place
        new_embed = await self.build_spreadsheet_embed(interaction.guild_id)
        await interaction.response.edit_message(embed=new_embed, view=self)


# =============================================================================
# 4. Cog Definition & Commands
# =============================================================================


class ChoresCog(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="post_dashboard",
        description="Spawns the live interactive chore spreadsheet",
    )
    @app_commands.default_permissions(administrator=True)
    async def post_dashboard(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        view = ChoreDashboardView(self.bot)
        embed = await view.build_spreadsheet_embed(interaction.guild_id)

        # Send publicly to the channel where command is executed
        await interaction.channel.send(embed=embed, view=view)
        await interaction.followup.send(
            "✅ Dashboard posted successfully!", ephemeral=True
        )

    @app_commands.command(
        name="my_chores",
        description="View your active assignments and missed hours",
    )
    async def my_chores(self, interaction: discord.Interaction):
        year, week, _ = datetime.now().isocalendar()
        week_str = f"{year}-W{week:02d}"

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
            embed.add_field(
                name="Assigned Tasks",
                value="No open chores this week!",
                inline=False,
            )
        else:
            for c in chores:
                embed.add_field(
                    name=f"#{c['chore_id']} {c['title']} ({c['hours']}h)",
                    value=f"Status: `{c['status'].upper()}`",
                    inline=False,
                )

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ChoresCog(bot))