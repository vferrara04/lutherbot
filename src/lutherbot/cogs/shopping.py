# src/lutherbot/cogs/shopping.py
import asyncio
from datetime import datetime
import discord
from discord import app_commands
from discord.ext import commands
from lutherbot import config
from lutherbot.cogs.helpers import (
    has_manager_role,
    get_or_fetch_channel,
    post_dashboard_to_channel,
    PaginatedDashboardView,
)


def has_food_role():
    """Restricts command execution strictly to members with the Food role."""
    async def predicate(interaction: discord.Interaction) -> bool:
        if config.FOOD_ROLE_ID:
            has_role = any(r.id == config.FOOD_ROLE_ID for r in interaction.user.roles)
        else:
            has_role = any(
                r.name.lower() in ("food", "food manager", "food team", "admin")
                for r in interaction.user.roles
            )

        if not has_role:
            await interaction.response.send_message(
                "⛔ You need the **Food** role to export and clear the shopping list.",
                ephemeral=True,
            )
            return False
        return True

    return app_commands.check(predicate)


class AddItemModal(discord.ui.Modal, title="Add to House Shopping List"):
    item_name = discord.ui.TextInput(
        label="Item Name",
        placeholder="e.g. Dawn Dish Soap, 2% Milk, Paper Towels",
        max_length=60,
    )
    quantity = discord.ui.TextInput(
        label="Quantity / Brand Notes",
        placeholder="e.g. 2 pack, Kirkland preferred",
        default="1",
        max_length=50,
    )

    def __init__(self, bot: commands.Bot, board_view: "ShoppingBoardView"):
        super().__init__()
        self.bot = bot
        self.board_view = board_view

    async def on_submit(self, interaction: discord.Interaction):
        await self.bot.db.add_shopping_item(
            guild_id=interaction.guild_id or 0,
            item_name=self.item_name.value.strip(),
            quantity=self.quantity.value.strip(),
            requested_by=interaction.user.id,
        )

        await interaction.response.send_message(
            f"✅ Added **{self.item_name.value}** (`{self.quantity.value}`) to the list!",
            ephemeral=True,
        )

        if interaction.message:
            new_embed = await self.board_view.build_shopping_embed(interaction.guild_id or 0)
            await interaction.message.edit(embed=new_embed, view=self.board_view)


class ShoppingBoardView(PaginatedDashboardView):
    """Persistent dashboard containing Add, Refresh, and Pagination controls."""

    def __init__(self, bot: commands.Bot):
        super().__init__(bot=bot, per_page=30, manager_only=False, timeout=None)

    async def build_embed(self, interaction: discord.Interaction | None = None) -> discord.Embed:
        guild_id = interaction.guild_id if interaction and interaction.guild_id else 0
        return await self.build_shopping_embed(guild_id)

    async def build_shopping_embed(self, guild_id: int = 0) -> discord.Embed:
        query = """
            SELECT s.item_name, s.quantity, u.first_name
            FROM shopping_items s
            LEFT JOIN users u ON s.requested_by = u.uid
            WHERE s.status = 'needed'
            ORDER BY s.id ASC;
        """
        async with self.bot.db.conn.execute(query) as cursor:
            items = await cursor.fetchall()

        embed = discord.Embed(
            title="🛒 House Grocery & Supply List",
            color=discord.Color.teal(),
            timestamp=datetime.utcnow(),
        )

        chunk, total_pages = self.paginate(items)
        if not items:
            embed.description = (
                "```text\nAll stocked up! No items requested right now.\n```\n"
                "*Click **Add Item** below to request groceries or supplies.*"
            )
            return embed

        lines = [
            f"{'Item':<20} | {'Qty':<10} | {'Requested By':<12}",
            "-" * 48,
        ]

        for it in chunk:
            name = it["item_name"][:19]
            qty = it["quantity"][:9]
            requester = (it["first_name"] or "Unknown")[:12]
            lines.append(f"{name:<20} | {qty:<10} | {requester:<12}")

        embed.description = (
            f"```text\n{chr(10).join(lines)}\n```\n"
            f"*Page {self.page + 1}/{total_pages} • Total items pending: **{len(items)}***"
        )
        embed.set_footer(text="Auto-clears when exported by the food manager")
        return embed

    @discord.ui.button(
        label="Add Item",
        style=discord.ButtonStyle.success,
        emoji="➕",
        custom_id="shop_btn_add_item",
        row=0,
    )
    async def add_item_click(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AddItemModal(self.bot, self))

    @discord.ui.button(
        label="Refresh",
        style=discord.ButtonStyle.secondary,
        emoji="🔄",
        custom_id="shop_btn_refresh_board",
        row=0,
    )
    async def refresh_click(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._refresh_display(interaction)

    @discord.ui.button(
        label="◀ Prev",
        style=discord.ButtonStyle.secondary,
        custom_id="shop_btn_prev_page",
        row=0,
    )
    async def prev_page_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._turn_page(interaction, -1)

    @discord.ui.button(
        label="Next ▶",
        style=discord.ButtonStyle.secondary,
        custom_id="shop_btn_next_page",
        row=0,
    )
    async def next_page_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._turn_page(interaction, 1)


class ShoppingCog(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="post_shopping_list",
        description="Spawns the permanent interactive shopping board",
    )
    @has_manager_role()
    async def post_shopping_list(self, interaction: discord.Interaction):
        view = ShoppingBoardView(self.bot)
        embed = await view.build_shopping_embed(interaction.guild_id or 0)
        await post_dashboard_to_channel(
            interaction,
            config.FOOD_REQUEST_CHANNEL_ID,
            view,
            embed,
            "✅ Shopping board posted!",
        )

    @app_commands.command(
        name="send_shopping_list",
        description="Exports pending grocery items to the private food channel with checkable reactions",
    )
    @has_food_role()
    async def send_shopping_list(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        items = await self.bot.db.fetch_and_reset_shopping_list(interaction.guild_id or 0)
        if not items:
            await interaction.followup.send(
                "🛒 The shopping list is empty. No new items have been added.",
                ephemeral=True,
            )
            return

        header_embed = discord.Embed(
            title="🛒 New Grocery Trip Checklist",
            description=(
                f"Exported by {interaction.user.mention} on **{datetime.now().strftime('%A, %b %d at %I:%M %p')}**\n"
                f"**{len(items)}** items total. React with ✅ to cross items off as you shop!"
            ),
            color=discord.Color.green(),
        )
        food_channel = await get_or_fetch_channel(self.bot, config.FOOD_CHANNEL_ID)
        await food_channel.send(embed=header_embed)

        for it in items:
            requester = f" *(req by {it['first_name']})*" if it["first_name"] else ""
            msg = await food_channel.send(f"▫️ **{it['item_name']}** — Qty: `{it['quantity']}`{requester}")
            await msg.add_reaction("✅")
            await asyncio.sleep(0.25)

        await interaction.followup.send(
            f"✅ Sent **{len(items)} items** to {food_channel.mention} and reset the board!",
            ephemeral=True,
        )

    async def _get_checklist_message(
        self, payload: discord.RawReactionActionEvent
    ) -> discord.Message | None:
        if payload.user_id == self.bot.user.id:
            return None
        if config.FOOD_CHANNEL_ID and payload.channel_id != config.FOOD_CHANNEL_ID:
            return None
        if str(payload.emoji) != "✅":
            return None

        channel = self.bot.get_channel(payload.channel_id)
        if not channel:
            return None

        try:
            return await channel.fetch_message(payload.message_id)
        except discord.NotFound:
            return None

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        message = await self._get_checklist_message(payload)
        if message and message.content.startswith("▫️"):
            cleaned = message.content.replace("▫️ ", "").strip()
            await message.edit(content=f"✅ ~~{cleaned}~~")

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        message = await self._get_checklist_message(payload)
        if not message:
            return
        reaction = discord.utils.get(message.reactions, emoji="✅")
        if reaction and reaction.count <= 1:
            content = message.content
            if content.startswith("✅ ~~") and content.endswith("~~"):
                await message.edit(content=f"▫️ {content[4:-2]}")


async def setup(bot: commands.Bot):
    await bot.add_cog(ShoppingCog(bot))