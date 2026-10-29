# src/lutherbot/cogs/chore_views.py
from datetime import datetime
import discord
import math
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


class PaginatedChoreSelectView(discord.ui.View):
    """Ephemeral view that paginates chore select menus 25 options at a time."""

    def __init__(
        self,
        bot: commands.Bot,
        chores: list,
        mode: str,
        manager_view: "ChoreManagerView",
        dashboard_message: discord.Message | None,
    ):
        super().__init__(timeout=120)
        self.bot = bot
        self.chores = chores
        self.mode = mode  # "edit" or "delete"
        self.manager_view = manager_view
        self.dashboard_message = dashboard_message

        self.page = 0
        self.per_page = 25
        self.total_pages = max(1, math.ceil(len(self.chores) / self.per_page))

        self._rebuild_components()

    def _rebuild_components(self):
        self.clear_items()

        start = self.page * self.per_page
        chunk = self.chores[start : start + self.per_page]

        options = []
        for c in chunk:
            if self.mode == "edit":
                desc = f"{c['hours']}h • Due {format_due_day(c['due_day'])}"
            else:
                desc = f"Delete #{c['cid']} ({c['hours']}h)"

            options.append(
                discord.SelectOption(
                    label=f"#{c['cid']} {c['title'][:40]}",
                    value=str(c["cid"]),
                    description=desc[:100],
                )
            )

        placeholder = (
            f"Select a chore to {self.mode} (Page {self.page + 1}/{self.total_pages})..."
        )
        select_menu = discord.ui.Select(
            placeholder=placeholder,
            options=options,
            row=0,
        )
        select_menu.callback = self.select_callback
        self.add_item(select_menu)

        # Only show pagination buttons if there are more than 25 chores
        if self.total_pages > 1:
            prev_btn = discord.ui.Button(
                label="◀ Prev",
                style=discord.ButtonStyle.secondary,
                disabled=(self.page <= 0),
                row=1,
            )
            prev_btn.callback = self.prev_page
            self.add_item(prev_btn)

            page_indicator = discord.ui.Button(
                label=f"Page {self.page + 1}/{self.total_pages}",
                style=discord.ButtonStyle.secondary,
                disabled=True,
                row=1,
            )
            self.add_item(page_indicator)

            next_btn = discord.ui.Button(
                label="Next ▶",
                style=discord.ButtonStyle.secondary,
                disabled=(self.page >= self.total_pages - 1),
                row=1,
            )
            next_btn.callback = self.next_page
            self.add_item(next_btn)

    async def prev_page(self, interaction: discord.Interaction):
        if self.page > 0:
            self.page -= 1
            self._rebuild_components()
            await interaction.response.edit_message(view=self)
        else:
            await interaction.response.defer()

    async def next_page(self, interaction: discord.Interaction):
        if self.page < self.total_pages - 1:
            self.page += 1
            self._rebuild_components()
            await interaction.response.edit_message(view=self)
        else:
            await interaction.response.defer()

    async def select_callback(self, select_inter: discord.Interaction):
        cid = int(select_inter.data["values"][0])
        chore = await self.bot.db.get_chore(cid)
        if not chore:
            await select_inter.response.send_message(
                "❌ Chore template not found.", ephemeral=True
            )
            return

        if self.mode == "edit":
            await select_inter.response.send_modal(
                EditChoreModal(self.bot, dict(chore), self.manager_view)
            )
        elif self.mode == "delete":
            await self.bot.db.delete_chore(cid)
            await select_inter.response.edit_message(
                content=f"🗑️ Deleted master chore **#{cid}** (`{chore['title']}`).",
                view=None,
            )
            new_embed = await self.manager_view.build_manager_embed()
            if self.dashboard_message:
                await self.dashboard_message.edit(
                    embed=new_embed, view=self.manager_view
                )


class ChoreManagerView(discord.ui.View):
    """Interactive management dashboard strictly for house managers."""

    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot
        self.page = 0
        self.per_page = 10  # 10 fields per page (well below Discord's 25-field limit)

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

    def _update_nav_buttons(self, total_pages: int):
        """Enable or disable the Prev/Next buttons based on current page."""
        self.prev_page_btn.disabled = self.page <= 0
        self.next_page_btn.disabled = self.page >= total_pages - 1

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
            self.page = 0
            self._update_nav_buttons(1)
            embed.description = "```\nNo master chores configured yet. Click 'Add Chore' below!\n```"
            return embed

        total_pages = max(1, math.ceil(len(chores) / self.per_page))
        # Clamp current page in case items were deleted
        self.page = max(0, min(self.page, total_pages - 1))
        self._update_nav_buttons(total_pages)

        start = self.page * self.per_page
        page_chores = chores[start : start + self.per_page]

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

    # --- ROW 0: Action Buttons ---

    @discord.ui.button(
        label="Add Chore",
        style=discord.ButtonStyle.success,
        emoji="➕",
        custom_id="chore_mgr_btn_add",
        row=0,
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
        row=0,
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

        select_view = PaginatedChoreSelectView(
            bot=self.bot,
            chores=chores,
            mode="edit",
            manager_view=self,
            dashboard_message=interaction.message,
        )

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
        row=0,
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

        select_view = PaginatedChoreSelectView(
            bot=self.bot,
            chores=chores,
            mode="delete",
            manager_view=self,
            dashboard_message=interaction.message,
        )

        await interaction.response.send_message(
            "⚠️ Select a chore to permanently delete:",
            view=select_view,
            ephemeral=True,
        )

    @discord.ui.button(
        label="Refresh",
        style=discord.ButtonStyle.secondary,
        emoji="🔄",
        custom_id="chore_mgr_btn_refresh",
        row=0,
    )
    async def refresh_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        new_embed = await self.build_manager_embed()
        await interaction.response.edit_message(embed=new_embed, view=self)

    # --- ROW 1: Dashboard Pagination Buttons ---

    @discord.ui.button(
        label="◀ Prev",
        style=discord.ButtonStyle.secondary,
        custom_id="chore_mgr_btn_prev",
        row=1,
    )
    async def prev_page_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if self.page > 0:
            self.page -= 1
        new_embed = await self.build_manager_embed()
        await interaction.response.edit_message(embed=new_embed, view=self)

    @discord.ui.button(
        label="Next ▶",
        style=discord.ButtonStyle.secondary,
        custom_id="chore_mgr_btn_next",
        row=1,
    )
    async def next_page_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        self.page += 1
        new_embed = await self.build_manager_embed()
        await interaction.response.edit_message(embed=new_embed, view=self)