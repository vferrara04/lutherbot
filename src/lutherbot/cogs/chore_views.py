# src/lutherbot/cogs/chore_views.py
from datetime import datetime
import discord
from discord.ext import commands
from lutherbot.cogs.helpers import (
    format_due_day,
    send_or_edit,
    make_jump_view,
    make_chore_options,
    PaginatedDashboardView,
    PaginatedSelectView,
)
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
        thread_title = f"Chore #{self.chore['title']} - {interaction.user.display_name}{partner_names}"

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

        thread, err = await spawn_review_thread(
            interaction=interaction,
            thread_title=thread_title,
            content=f"👋 {mentions}",
            embed=embed,
            view=ThreadReviewView(),
        )

        if not thread:
            await send_or_edit(interaction, f"❌ **Could not create submission ticket**:\n{err}")
            return

        await self.bot.db.link_thread(
            chore_id=self.chore["chore_id"],
            user_ids=target_uids,
            week=self.week,
            thread_id=thread.id,
        )

        jump_view = make_jump_view(f"Jump to #{thread.name}", thread.jump_url, emoji="🚀")
        await send_or_edit(
            interaction,
            "✅ Submission ticket thread created! Click the button below to upload your photo proof:",
            view=jump_view,
        )

    @discord.ui.button(label="Just Myself", style=discord.ButtonStyle.secondary, emoji="👤")
    async def just_me(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._spawn_thread(interaction, target_uids=[self.user_id], is_shared=False)

    @discord.ui.button(label="Both of Us", style=discord.ButtonStyle.primary, emoji="👥")
    async def both_of_us(self, interaction: discord.Interaction, button: discord.ui.Button):
        target_uids = [self.user_id] + [p["uid"] for p in self.partners]
        await self._spawn_thread(interaction, target_uids=target_uids, is_shared=True)


class ChoreManagerView(PaginatedDashboardView):
    """Interactive management dashboard strictly for house managers."""

    def __init__(self, bot: commands.Bot):
        super().__init__(bot=bot, per_page=10, manager_only=True, timeout=None)

    async def build_embed(self, interaction: discord.Interaction | None = None) -> discord.Embed:
        return await self.build_manager_embed()

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

        page_chores, total_pages = self.paginate(chores)
        if not chores:
            embed.description = "```\nNo master chores configured yet. Click 'Add Chore' below!\n```"
            return embed

        for c in page_chores:
            day_str = f"Due: {format_due_day(c['due_day'])}"
            embed.add_field(
                name=f"#{c['cid']} {c['title']} (`{c['hours']}h`)",
                value=f"{c['description'] or 'No instructions'}\n*{day_str}*",
                inline=False,
            )

        embed.set_footer(
            text=f"Page {self.page + 1}/{total_pages} ({len(chores)} total chores) • Manager Role Only"
        )
        return embed

    @discord.ui.button(
        label="Add Chore",
        style=discord.ButtonStyle.success,
        emoji="➕",
        custom_id="chore_mgr_btn_add",
        row=0,
    )
    async def add_chore_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            AddChoreModal(self.bot, self, dashboard_message=interaction.message)
        )

    @discord.ui.button(
        label="Edit Chore",
        style=discord.ButtonStyle.primary,
        emoji="✏️",
        custom_id="chore_mgr_btn_edit",
        row=0,
    )
    async def edit_chore_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        chores = await self.bot.db.get_all_chores()
        if not chores:
            await interaction.response.send_message("❌ No master chores exist yet to edit.", ephemeral=True)
            return

        dashboard_msg = interaction.message

        async def on_picked(s_inter: discord.Interaction, val: str):
            chore = await self.bot.db.get_chore(int(val))
            if not chore:
                await s_inter.response.send_message("❌ Chore template not found.", ephemeral=True)
                return
            await s_inter.response.send_modal(
                EditChoreModal(self.bot, dict(chore), self, dashboard_message=dashboard_msg)
            )

        view = PaginatedSelectView(
            options=make_chore_options(chores, mode="edit"),
            placeholder="Select a chore to edit...",
            on_select=on_picked,
        )
        await interaction.response.send_message(
            "Select which master chore you would like to edit:",
            view=view,
            ephemeral=True,
        )

    @discord.ui.button(
        label="Delete Chore",
        style=discord.ButtonStyle.danger,
        emoji="🗑️",
        custom_id="chore_mgr_btn_delete",
        row=0,
    )
    async def delete_chore_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        chores = await self.bot.db.get_all_chores()
        if not chores:
            await interaction.response.send_message("❌ No master chores exist to delete.", ephemeral=True)
            return

        dashboard_msg = interaction.message

        async def on_picked(s_inter: discord.Interaction, val: str):
            cid = int(val)
            chore = await self.bot.db.get_chore(cid)
            if not chore:
                await s_inter.response.send_message("❌ Chore template not found.", ephemeral=True)
                return

            await self.bot.db.delete_chore(cid)
            await s_inter.response.edit_message(
                content=f"🗑️ Deleted master chore **#{cid}** (`{chore['title']}`).",
                view=None,
            )
            if dashboard_msg:
                await dashboard_msg.edit(embed=await self.build_manager_embed(), view=self)

        view = PaginatedSelectView(
            options=make_chore_options(chores, mode="delete"),
            placeholder="Select a chore to delete...",
            on_select=on_picked,
        )
        await interaction.response.send_message(
            "⚠️ Select a chore to permanently delete:",
            view=view,
            ephemeral=True,
        )

    @discord.ui.button(
        label="Refresh",
        style=discord.ButtonStyle.secondary,
        emoji="🔄",
        custom_id="chore_mgr_btn_refresh",
        row=0,
    )
    async def refresh_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._refresh_display(interaction)

    @discord.ui.button(
        label="◀ Prev",
        style=discord.ButtonStyle.secondary,
        custom_id="chore_mgr_btn_prev",
        row=1,
    )
    async def prev_page_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._turn_page(interaction, -1)

    @discord.ui.button(
        label="Next ▶",
        style=discord.ButtonStyle.secondary,
        custom_id="chore_mgr_btn_next",
        row=1,
    )
    async def next_page_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._turn_page(interaction, 1)