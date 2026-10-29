# src/lutherbot/cogs/modals.py
import discord
from discord.ext import commands
from lutherbot.cogs.helpers import format_due_day, parse_due_day


class ChoreModal(discord.ui.Modal):
    """Unified modal for creating or editing a master chore template."""

    def __init__(
        self,
        bot: commands.Bot,
        chore: dict | None = None,
        parent_view=None,
        dashboard_message: discord.Message | None = None,
    ):
        is_edit = chore is not None
        super().__init__(
            title=f"Edit Chore #{chore['cid']}" if is_edit else "Add Master House Chore"
        )
        self.bot = bot
        self.chore = chore
        self.parent_view = parent_view
        self.dashboard_message = dashboard_message

        self.chore_title = discord.ui.TextInput(
            label="Chore Title",
            placeholder="e.g. Kitchen Deep Clean",
            default=chore["title"] if is_edit else "",
            max_length=60,
        )
        self.description = discord.ui.TextInput(
            label="Checklist / Instructions",
            placeholder="Wipe counters, sanitize sink, take out compost...",
            default=(chore["description"] or "") if is_edit else "",
            style=discord.TextStyle.paragraph,
            max_length=300,
            required=False,
        )
        self.hours = discord.ui.TextInput(
            label="Credit Hours",
            placeholder="2",
            default=str(chore["hours"]) if is_edit else "1",
            max_length=3,
        )
        self.due_day = discord.ui.TextInput(
            label="Due Day of Week",
            placeholder="e.g. Sunday, Monday, Tuesday... (or blank)",
            default=(
                ""
                if not is_edit or chore["due_day"] is None
                else format_due_day(chore["due_day"])
            ),
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
        title_clean = self.chore_title.value.strip()
        desc_clean = self.description.value.strip()
        day_text = format_due_day(day)

        if self.chore is None:
            cid = await self.bot.db.add_chore(
                title=title_clean,
                description=desc_clean,
                hours=hrs,
                due_day=day,
            )
            action_msg = f"✅ Created Chore **#{cid}**: `{title_clean}` ({hrs}h credit, Due: **{day_text}**)!"
        else:
            cid = self.chore["cid"]
            await self.bot.db.edit_chore(
                cid=cid,
                title=title_clean,
                description=desc_clean,
                hours=hrs,
                due_day=day,
            )
            action_msg = f"✅ Updated Chore **#{cid}**: `{title_clean}` ({hrs}h credit, Due: **{day_text}**)!"

        await interaction.response.send_message(action_msg, ephemeral=True)

        target_msg = self.dashboard_message or interaction.message
        if self.parent_view and target_msg:
            try:
                new_embed = await self.parent_view.build_manager_embed()
                await target_msg.edit(embed=new_embed, view=self.parent_view)
            except discord.HTTPException:
                pass


class AddChoreModal(ChoreModal):
    def __init__(self, bot: commands.Bot, parent_view=None, dashboard_message: discord.Message | None = None):
        super().__init__(bot, chore=None, parent_view=parent_view, dashboard_message=dashboard_message)


class EditChoreModal(ChoreModal):
    def __init__(self, bot: commands.Bot, chore: dict, parent_view=None, dashboard_message: discord.Message | None = None):
        super().__init__(bot, chore=chore, parent_view=parent_view, dashboard_message=dashboard_message)
