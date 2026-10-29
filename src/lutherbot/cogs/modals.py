# src/lutherbot/cogs/modals.py
import discord
from discord.ext import commands
from lutherbot.cogs.helpers import format_due_day, parse_due_day


class AddChoreModal(discord.ui.Modal, title="Add Master House Chore"):
    chore_title = discord.ui.TextInput(
        label="Chore Title",
        placeholder="e.g. Kitchen Deep Clean",
        max_length=60,
    )
    description = discord.ui.TextInput(
        label="Checklist / Instructions",
        placeholder="Wipe counters, sanitize sink, take out compost...",
        style=discord.TextStyle.paragraph,
        max_length=300,
        required=False,
    )
    hours = discord.ui.TextInput(
        label="Credit Hours",
        placeholder="2",
        default="1",
        max_length=3,
    )
    due_day = discord.ui.TextInput(
        label="Due Day of Week",
        placeholder="e.g. Sunday, Monday, Tuesday... (or blank)",
        required=False,
        max_length=15,
    )

    def __init__(self, bot: commands.Bot, parent_view=None, dashboard_message: discord.Message | None = None):
        super().__init__()
        self.bot = bot
        self.parent_view = parent_view
        self.dashboard_message = dashboard_message

    async def on_submit(self, interaction: discord.Interaction):
        try:
            hrs = max(1, int(self.hours.value.strip()))
        except ValueError:
            hrs = 1

        day = parse_due_day(self.due_day.value) if self.due_day.value.strip() else None

        cid = await self.bot.db.add_chore(
            title=self.chore_title.value.strip(),
            description=self.description.value.strip(),
            hours=hrs,
            due_day=day,
        )

        day_text = format_due_day(day)
        await interaction.response.send_message(
            f"✅ Created Chore **#{cid}**: `{self.chore_title.value}` ({hrs}h credit, Due: **{day_text}**)!",
            ephemeral=True,
        )

        target_msg = self.dashboard_message or interaction.message
        if self.parent_view and target_msg:
            try:
                new_embed = await self.parent_view.build_manager_embed()
                await target_msg.edit(embed=new_embed, view=self.parent_view)
            except discord.HTTPException:
                pass


class EditChoreModal(discord.ui.Modal):

    def __init__(self, bot: commands.Bot, chore: dict, parent_view=None, dashboard_message: discord.Message | None = None):
        super().__init__(title=f"Edit Chore #{chore['cid']}")
        self.bot = bot
        self.cid = chore["cid"]
        self.parent_view = parent_view
        self.dashboard_message = dashboard_message

        self.chore_title = discord.ui.TextInput(
            label="Chore Title",
            default=chore["title"],
            max_length=60,
        )
        self.description = discord.ui.TextInput(
            label="Checklist / Instructions",
            default=chore["description"] or "",
            style=discord.TextStyle.paragraph,
            max_length=300,
            required=False,
        )
        self.hours = discord.ui.TextInput(
            label="Credit Hours",
            default=str(chore["hours"]),
            max_length=3,
        )
        self.due_day = discord.ui.TextInput(
            label="Due Day of Week",
            default="" if chore["due_day"] is None else format_due_day(chore["due_day"]),
            placeholder="e.g. Sunday, Monday...",
            required=False,
            max_length=15,
        )

        self.add_item(self.chore_title)
        self.add_item(self.description)
        self.add_item(self.hours)
        self.add_item(self.due_day)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            hrs = max(1, int(self.hours.value.strip()))
        except ValueError:
            hrs = 1

        day = parse_due_day(self.due_day.value) if self.due_day.value.strip() else None

        await self.bot.db.edit_chore(
            cid=self.cid,
            title=self.chore_title.value.strip(),
            description=self.description.value.strip(),
            hours=hrs,
            due_day=day,
        )

        day_text = format_due_day(day)
        await interaction.response.send_message(
            f"✅ Updated Chore **#{self.cid}**: `{self.chore_title.value}` ({hrs}h credit, Due: **{day_text}**)!",
            ephemeral=True,
        )

        target_msg = self.dashboard_message or interaction.message
        if self.parent_view and target_msg:
            try:
                new_embed = await self.parent_view.build_manager_embed()
                await target_msg.edit(embed=new_embed, view=self.parent_view)
            except discord.HTTPException:
                pass
