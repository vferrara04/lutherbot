# src/lutherbot/cogs/shopping.py
import asyncio
from datetime import datetime
import discord
from discord import app_commands
from discord.ext import commands
from lutherbot import config
from lutherbot.cogs.helpers import has_manager_role, get_or_fetch_channel


def has_food_role():
    """Restricts command execution strictly to members with the Food role."""

    async def predicate(interaction: discord.Interaction) -> bool:
        if config.FOOD_ROLE_ID:
            has_role = any(
                r.id == config.FOOD_ROLE_ID for r in interaction.user.roles
            )
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


# =============================================================================
# 1. Add Item Popup Modal
# =============================================================================


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
        # 1. Insert item into SQLite
        await self.bot.db.add_shopping_item(
            guild_id=interaction.guild_id or 0,
            item_name=self.item_name.value.strip(),
            quantity=self.quantity.value.strip(),
            requested_by=interaction.user.id,
        )

        # 2. Confirm to the user ephemerally
        await interaction.response.send_message(
            f"✅ Added **{self.item_name.value}** (`{self.quantity.value}`) to the list!",
            ephemeral=True,
        )

        # 3. Update the public board message in place
        if interaction.message:
            new_embed = await self.board_view.build_shopping_embed(
                interaction.guild_id or 0
            )
            await interaction.message.edit(embed=new_embed, view=self.board_view)


# =============================================================================
# 2. Streamlined Shopping Board View
# =============================================================================


class ShoppingBoardView(discord.ui.View):
    """Persistent dashboard containing only Add and Refresh controls."""

    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    async def build_shopping_embed(self, guild_id: int) -> discord.Embed:
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

        if not items:
            embed.description = (
                "```text\nAll stocked up! No items requested right now.\n```\n"
                "*Click **Add Item** below to request groceries or supplies.*"
            )
            return embed

        # Monospace spreadsheet layout: Item (20) | Qty (10) | Requested By (12)
        lines = [
            f"{'Item':<20} | {'Qty':<10} | {'Requested By':<12}",
            "-" * 48,
        ]

        for it in items:
            name = (
                it["item_name"][:19]
                if len(it["item_name"]) > 19
                else it["item_name"]
            )
            qty = (
                it["quantity"][:9]
                if len(it["quantity"]) > 9
                else it["quantity"]
            )
            requester = it["first_name"] or "Unknown"
            requester = requester[:12]

            lines.append(f"{name:<20} | {qty:<10} | {requester:<12}")

        table_text = "\n".join(lines)
        embed.description = (
            f"```text\n{table_text}\n```\n"
            f"*Total items pending: **{len(items)}***"
        )
        embed.set_footer(text="Auto-clears when exported by the food manager")
        return embed

    @discord.ui.button(
        label="Add Item",
        style=discord.ButtonStyle.success,
        emoji="➕",
        custom_id="shop_btn_add_item",
    )
    async def add_item_click(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.send_modal(AddItemModal(self.bot, self))

    @discord.ui.button(
        label="Refresh",
        style=discord.ButtonStyle.secondary,
        emoji="🔄",
        custom_id="shop_btn_refresh_board",
    )
    async def refresh_click(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        new_embed = await self.build_shopping_embed(interaction.guild_id or 0)
        await interaction.response.edit_message(embed=new_embed, view=self)


# =============================================================================
# 3. Cog Definition & Export Command
# =============================================================================


class ShoppingCog(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot
    

    @app_commands.command(
        name="post_shopping_list",
        description="Spawns the permanent interactive shopping board",
    )
    @app_commands.default_permissions(manage_guild=True)
    @has_manager_role()
    async def post_shopping_list(self, interaction: discord.Interaction):
        print(
        f"DEBUG: FOOD_REQUEST_CHANNEL_ID is {config.FOOD_REQUEST_CHANNEL_ID} (type: {type(config.FOOD_REQUEST_CHANNEL_ID)})"
        )
        food_request_channel = await get_or_fetch_channel(self.bot, config.FOOD_REQUEST_CHANNEL_ID)
        await interaction.response.defer(ephemeral=True)
        view = ShoppingBoardView(self.bot)
        embed = await view.build_shopping_embed(interaction.guild_id or 0)
        await food_request_channel.send(embed=embed, view=view)
        await interaction.followup.send(
            "✅ Shopping board posted!", ephemeral=True
        )

    @app_commands.command(
        name="send_shopping_list",
        description="Exports pending grocery items to the private food channel with checkable reactions",
    )
    @app_commands.default_permissions(manage_guild=True)
    @has_food_role()
    async def send_shopping_list(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        # Fetch and archive pending items in SQLite
        items = await self.bot.db.fetch_and_reset_shopping_list(
            interaction.guild_id or 0
        )
        if not items:
            await interaction.followup.send(
                "🛒 The shopping list is empty. No new items have been added.",
                ephemeral=True,
            )
            return

        # 1. Post batch header in the private food channel
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

        # 2. Post each item as an individual checklist message
        for it in items:
            requester = (
                f" *(req by {it['first_name']})*" if it["first_name"] else ""
            )
            msg = await food_channel.send(
                f"▫️ **{it['item_name']}** — Qty: `{it['quantity']}`{requester}"
            )
            await msg.add_reaction("✅")
            await asyncio.sleep(0.25)

        await interaction.followup.send(
            f"✅ Sent **{len(items)} items** to {food_channel.mention} and reset the board!",
            ephemeral=True,
        )

    # =========================================================================
    # 4. Reaction Strikethrough Listeners
    # =========================================================================

    @commands.Cog.listener()
    async def on_raw_reaction_add(
        self, payload: discord.RawReactionActionEvent
    ):
        if payload.user_id == self.bot.user.id:
            return
        if config.FOOD_CHANNEL_ID and payload.channel_id != config.FOOD_CHANNEL_ID:
            return
        if str(payload.emoji) != "✅":
            return

        channel = self.bot.get_channel(payload.channel_id)
        if not channel:
            return

        try:
            message = await channel.fetch_message(payload.message_id)
        except discord.NotFound:
            return

        if message.content.startswith("▫️"):
            cleaned = message.content.replace("▫️ ", "").strip()
            await message.edit(content=f"✅ ~~{cleaned}~~")

    @commands.Cog.listener()
    async def on_raw_reaction_remove(
        self, payload: discord.RawReactionActionEvent
    ):
        if config.FOOD_CHANNEL_ID and payload.channel_id != config.FOOD_CHANNEL_ID:
            return
        if str(payload.emoji) != "✅":
            return

        channel = self.bot.get_channel(payload.channel_id)
        if not channel:
            return

        try:
            message = await channel.fetch_message(payload.message_id)
        except discord.NotFound:
            return

        reaction = discord.utils.get(message.reactions, emoji="✅")
        if reaction and reaction.count <= 1:
            content = message.content
            if content.startswith("✅ ~~") and content.endswith("~~"):
                restored = content[4:-2]
                await message.edit(content=f"▫️ {restored}")


async def setup(bot: commands.Bot):
    await bot.add_cog(ShoppingCog(bot))
