# src/lutherbot/cogs/chore_views.py
from datetime import datetime
import discord
from discord.ext import commands
from lutherbot.cogs.helpers import check_is_manager, format_due_day
from lutherbot.cogs.reviews import ThreadReviewView, spawn_review_thread
from lutherbot.cogs.modals import AddChoreModal, EditChoreModal


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
        partner_names = " & Partner" if is_shared else ""
        thread_title = f"Chore #{self.chore['chore_id']} - {interaction.user.display_name}{partner_names}"

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

        review_view = ThreadReviewView()

        thread, err = await spawn_review_thread(
            interaction=interaction,
            thread_title=thread_title,
            content=f"👋 {mentions}",
            embed=embed,
            view=review_view,
        )

        if not thread:
            err_msg = f"❌ **Could not create submission ticket**:\n{err}"
            if interaction.response.is_done():
                await interaction.followup.send(err_msg, ephemeral=True)
            elif interaction.message:
                await interaction.response.edit_message(content=err_msg, view=None)
            else:
                await interaction.response.send_message(err_msg, ephemeral=True)
            return

        await self.bot.db.link_thread(
            chore_id=self.chore["chore_id"],
            user_ids=target_uids,
            week=self.week,
            thread_id=thread.id,
        )

        # Attach direct clickable jump button
        jump_view = discord.ui.View()
        jump_view.add_item(
            discord.ui.Button(
                label=f"Jump to #{thread.name}",
                url=thread.jump_url,
                style=discord.ButtonStyle.link,
                emoji="🚀",
            )
        )

        msg_text = "✅ Submission ticket thread created! Click the button below to upload your photo proof:"
        if interaction.response.is_done():
            await interaction.followup.send(
                msg_text,
                view=jump_view,
                ephemeral=True,
            )
        elif interaction.message is not None:
            await interaction.response.edit_message(
                content=msg_text,
                view=jump_view,
            )
        else:
            await interaction.response.send_message(
                msg_text,
                view=jump_view,
                ephemeral=True,
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


class ChoreManagerView(discord.ui.View):
    """Interactive management dashboard strictly for house managers."""

    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not check_is_manager(interaction.user, interaction.guild):
            await interaction.response.send_message(
                "⛔ **Restricted**: Only members with the **Manager** role can modify chore templates.",
                ephemeral=True,
            )
            return False
        return True

    def _get_current_week(self) -> str:
        year, week, _ = datetime.now().isocalendar()
        return f"{year}-W{week:02d}"

    async def build_manager_embed(self) -> discord.Embed:
        chores = await self.bot.db.get_all_chores()

        embed = discord.Embed(
            title="🛠️ Master Chore Templates Manager",
            description=(
                "Master chore templates definition board.\n"
                "• **Add Chore**: create master chore\n"
                "• **Edit Chore**: update requirements & hours\n"
                "• **Delete Chore**: permanently delete template"
            ),
            color=discord.Color.teal(),
            timestamp=datetime.utcnow(),
        )

        if not chores:
            embed.description = "```\nNo master chores configured yet. Click 'Add Chore' below!\n```"
            return embed

        for c in chores:
            day_str = f"Due: {format_due_day(c['due_day'])}"
            embed.add_field(
                name=f"#{c['cid']} {c['title']} (`{c['hours']}h`)",
                value=f"{c['description'] or 'No instructions'}\n*{day_str}*",
                inline=False,
            )

        embed.set_footer(text="Manager Role Only • Auto-refreshes on actions")
        return embed

    @discord.ui.button(
        label="Add Chore",
        style=discord.ButtonStyle.success,
        emoji="➕",
        custom_id="chore_mgr_btn_add",
    )
    async def add_chore_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.send_modal(AddChoreModal(self.bot, self))

    @discord.ui.button(
        label="Edit Chore",
        style=discord.ButtonStyle.primary,
        emoji="✏️",
        custom_id="chore_mgr_btn_edit",
    )
    async def edit_chore_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        chores = await self.bot.db.get_all_chores()
        if not chores:
            await interaction.response.send_message(
                "❌ No master chores exist yet to edit.", ephemeral=True
            )
            return

        options = [
            discord.SelectOption(
                label=f"#{c['cid']} {c['title'][:40]}",
                value=str(c["cid"]),
                description=f"{c['hours']}h • Due {format_due_day(c['due_day'])}",
            )
            for c in chores[:25]
        ]

        select_view = discord.ui.View(timeout=60)
        select_menu = discord.ui.Select(
            placeholder="Select a chore to edit...",
            options=options,
        )

        async def select_callback(select_inter: discord.Interaction):
            cid = int(select_menu.values[0])
            chore = await self.bot.db.get_chore(cid)
            if not chore:
                await select_inter.response.send_message(
                    "❌ Chore template not found.", ephemeral=True
                )
                return
            await select_inter.response.send_modal(
                EditChoreModal(self.bot, dict(chore), self)
            )

        select_menu.callback = select_callback
        select_view.add_item(select_menu)

        await interaction.response.send_message(
            "Select which master chore you would like to edit:",
            view=select_view,
            ephemeral=True,
        )

    @discord.ui.button(
        label="Delete Chore",
        style=discord.ButtonStyle.danger,
        emoji="🗑️",
        custom_id="chore_mgr_btn_delete",
    )
    async def delete_chore_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        chores = await self.bot.db.get_all_chores()
        if not chores:
            await interaction.response.send_message(
                "❌ No master chores exist to delete.", ephemeral=True
            )
            return

        options = [
            discord.SelectOption(
                label=f"#{c['cid']} {c['title'][:40]}",
                value=str(c["cid"]),
                description=f"Delete #{c['cid']} ({c['hours']}h)",
            )
            for c in chores[:25]
        ]

        select_view = discord.ui.View(timeout=60)
        select_menu = discord.ui.Select(
            placeholder="Select a chore to permanently delete...",
            options=options,
        )

        async def select_callback(select_inter: discord.Interaction):
            cid = int(select_menu.values[0])
            chore = await self.bot.db.get_chore(cid)
            if not chore:
                await select_inter.response.send_message(
                    "❌ Chore template not found.", ephemeral=True
                )
                return

            await self.bot.db.delete_chore(cid)
            await select_inter.response.send_message(
                f"🗑️ Deleted master chore **#{cid}** (`{chore['title']}`).",
                ephemeral=True,
            )
            new_embed = await self.build_manager_embed()
            if interaction.message:
                await interaction.message.edit(embed=new_embed, view=self)

        select_menu.callback = select_callback
        select_view.add_item(select_menu)

        await interaction.response.send_message(
            "⚠️ Select a chore to delete:",
            view=select_view,
            ephemeral=True,
        )

    @discord.ui.button(
        label="Refresh",
        style=discord.ButtonStyle.secondary,
        emoji="🔄",
        custom_id="chore_mgr_btn_refresh",
    )
    async def refresh_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        new_embed = await self.build_manager_embed()
        await interaction.response.edit_message(embed=new_embed, view=self)
