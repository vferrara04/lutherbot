# src/lutherbot/cogs/makeups.py
from datetime import datetime
import discord
from discord import app_commands
from discord.ext import commands
from lutherbot import config
from lutherbot.cogs.chores import (
    ThreadReviewView,  # Reuses existing review buttons
)


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
                "When complete, click **'Submit Makeup Proof'** on the board to spawn your review thread."
            ),
            view=None,
        )


class MakeupBoardView(discord.ui.View):

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
            "*Claim an open task to work off delinquent missed chore hours.*"
        )
        return embed

    @discord.ui.button(
        label="Claim Bounty",
        style=discord.ButtonStyle.success,
        emoji="✋",
        custom_id="makeup_btn_claim",
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
        label="Submit Makeup Proof",
        style=discord.ButtonStyle.primary,
        emoji="📸",
        custom_id="makeup_btn_submit",
    )
    async def submit_makeup_proof(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        # Locate chores claimed by this user that are still pending proof
        query = """
            SELECT m.mid, m.cid, m.week, c.title, c.hours, m.thread_id
            FROM makeup_chores m
            JOIN chores c ON m.cid = c.cid
            WHERE m.uid = ? AND m.status = 'claimed';
        """
        async with self.bot.db.conn.execute(query, (interaction.user.id,)) as cur:
            claimed_tasks = await cur.fetchall()

        if not claimed_tasks:
            await interaction.response.send_message(
                "⚠️ You don't have any claimed makeup chores awaiting proof.",
                ephemeral=True,
            )
            return

        task = claimed_tasks[0]
        if task["thread_id"]:
            url = f"https://discord.com/channels/{interaction.guild_id}/{task['thread_id']}"
            await interaction.response.send_message(
                f"⚠️ Your submission ticket is already open: [Jump to Thread]({url})",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        submissions_channel = interaction.guild.get_channel(config.SUBMISSION_CHANNEL_ID)
        thread = await submissions_channel.create_thread(
            name=f"Makeup #{task['mid']} - {interaction.user.display_name}",
            auto_archive_duration=1440,
            type=discord.ChannelType.public_thread,
        )

        await self.bot.db.link_makeup_thread(task["mid"], thread.id)

        embed = discord.Embed(
            title=f"🧹 Makeup Review: {task['title']}",
            description=(
                f"**Claimed By:** {interaction.user.mention}\n"
                f"**Debt Credit:** `{task['hours']} hrs`\n\n"
                "📸 Upload photo proof below. Managers will review and approve via the buttons."
            ),
            color=discord.Color.gold(),
        )
        await thread.send(
            content=f"👋 {interaction.user.mention}",
            embed=embed,
            view=ThreadReviewView(),
        )

        await interaction.followup.send(
            f"✅ Ticket opened: [Jump to #{thread.name}]({thread.jump_url})",
            ephemeral=True,
        )

    @discord.ui.button(
        label="Refresh Board",
        style=discord.ButtonStyle.secondary,
        emoji="🔄",
        custom_id="makeup_btn_refresh",
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
        name="makeup_post_board", description="Spawn the live makeup chore bounty board"
    )
    @app_commands.default_permissions(administrator=True)
    async def makeup_post_board(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        view = MakeupBoardView(self.bot)
        embed = await view.build_board_embed()
        await interaction.channel.send(embed=embed, view=view)
        await interaction.followup.send("✅ Makeup board posted!", ephemeral=True)

    @app_commands.command(
        name="makeup_add", description="Add an extra chore directly to the makeup pool"
    )
    @app_commands.describe(
        chore_id="Chore ID template to spawn as a bounty",
        week="Week identifier (e.g. 2026-W41)",
    )
    @app_commands.default_permissions(administrator=True)
    async def makeup_add(
        self, interaction: discord.Interaction, chore_id: int, week: str
    ):
        chore = await self.bot.db.get_chore(chore_id)
        if not chore:
            await interaction.response.send_message(
                f"❌ Chore template `#{chore_id}` does not exist.", ephemeral=True
            )
            return

        mid = await self.bot.db.add_makeup_chore(cid=chore_id, week=week)
        await interaction.response.send_message(
            f"✅ Created Makeup Bounty **#{mid}** (`{chore['title']}` - {chore['hours']}h credit) for week `{week}`.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(MakeupsCog(bot))