# src/lutherbot/cogs/users.py
from datetime import datetime
import math
import discord
from discord import app_commands
from discord.ext import commands
from lutherbot.cogs.helpers import has_manager_role


class RosterPaginationView(discord.ui.View):
    """Paginates the /roster table if there are more than 40 members."""

    def __init__(self, members: list):
        super().__init__(timeout=120)
        self.members = members
        self.page = 0
        self.per_page = 40
        self.total_pages = max(1, math.ceil(len(self.members) / self.per_page))
        self._update_buttons()

    def _update_buttons(self):
        self.prev_btn.disabled = self.page <= 0
        self.next_btn.disabled = self.page >= self.total_pages - 1

    def build_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🏠 House Co-op Roster",
            color=discord.Color.dark_theme(),
            timestamp=datetime.utcnow(),
        )
        if not self.members:
            embed.description = "No members registered yet. Use `/register` to sign up!"
            return embed

        start = self.page * self.per_page
        chunk = self.members[start : start + self.per_page]

        lines = [
            f"{'Member':<18} | {'Debt':<6} | {'Discord ID':<18}",
            "-" * 48,
        ]

        for m in chunk:
            full_name = f"{m['first_name']} {m['last_name']}"[:17]
            debt = f"{m['missed_chore_hours']}h"
            uid_str = str(m["uid"])
            lines.append(f"{full_name:<18} | {debt:<6} | {uid_str:<18}")

        embed.description = (
            f"```text\n{chr(10).join(lines)}\n```\n"
            f"*Page {self.page + 1}/{self.total_pages} • Total registered: {len(self.members)}*"
        )
        return embed

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 0:
            self.page -= 1
            self._update_buttons()
            await interaction.response.edit_message(embed=self.build_embed(), view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page < self.total_pages - 1:
            self.page += 1
            self._update_buttons()
            await interaction.response.edit_message(embed=self.build_embed(), view=self)
        else:
            await interaction.response.defer()


class UsersCog(commands.Cog):
    """Cog for managing house member registration and roster."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="register",
        description="Register yourself in the house chore roster",
    )
    @app_commands.describe(
        first_name="Your real first name",
        last_name="Your real last name",
    )
    async def register(
        self,
        interaction: discord.Interaction,
        first_name: str,
        last_name: str,
    ):
        """Allows any housemate to register their profile with their Discord account."""
        first_clean = first_name.strip().title()
        last_clean = last_name.strip().title()

        if not first_clean or not last_clean:
            await interaction.response.send_message(
                "❌ Please provide both a valid first and last name.",
                ephemeral=True,
            )
            return

        existing = await self.bot.db.get_user(interaction.user.id)
        current_debt = existing["missed_chore_hours"] if existing else 0

        await self.bot.db.upsert_user(
            user_id=interaction.user.id,
            first_name=first_clean,
            last_name=last_clean,
            missed_chore_hours=current_debt,
        )

        embed = discord.Embed(
            title="✅ Profile Registered",
            description=f"Welcome to the house roster, **{first_clean} {last_clean}**!",
            color=discord.Color.green(),
            timestamp=datetime.utcnow(),
        )
        embed.add_field(
            name="Discord Account",
            value=f"{interaction.user.mention} (`{interaction.user.id}`)",
            inline=True,
        )
        embed.add_field(
            name="Missed Debt Hours",
            value=f"`{current_debt} hrs`",
            inline=True,
        )
        embed.set_footer(text="Use /my_chores to view your weekly assignments.")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="add_user",
        description="Manager command: Register or update a housemate in the roster",
    )
    @app_commands.describe(
        member="Discord member to register",
        first_name="Their real first name",
        last_name="Their real last name",
        initial_debt_hours="Starting delinquent debt hours (default: 0)",
    )
    @has_manager_role()
    async def add_user(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        first_name: str,
        last_name: str,
        initial_debt_hours: int = 0,
    ):
        """Allows house managers/admins to add any housemate to the roster."""
        first_clean = first_name.strip().title()
        last_clean = last_name.strip().title()

        if not first_clean or not last_clean:
            await interaction.response.send_message(
                "❌ First name and last name cannot be empty.",
                ephemeral=True,
            )
            return

        debt = max(0, initial_debt_hours)

        await self.bot.db.upsert_user(
            user_id=member.id,
            first_name=first_clean,
            last_name=last_clean,
            missed_chore_hours=debt,
        )

        embed = discord.Embed(
            title="👤 Housemate Added to Roster",
            description=f"Successfully registered **{first_clean} {last_clean}**.",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow(),
        )
        embed.add_field(
            name="Member",
            value=f"{member.mention} (`{member.id}`)",
            inline=True,
        )
        embed.add_field(
            name="Starting Debt",
            value=f"`{debt} hrs`",
            inline=True,
        )
        embed.set_footer(
            text=f"Added by {interaction.user.display_name}"
        )

        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="roster",
        description="View all registered housemates and their debt hours",
    )
    @has_manager_role()
    async def roster(self, interaction: discord.Interaction):
        """Displays the entire housemate roster and debt standings."""
        members = await self.bot.db.get_all_users()
        view = RosterPaginationView(members)
        embed = view.build_embed()

        if view.total_pages > 1:
            await interaction.response.send_message(embed=embed, view=view)
        else:
            await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="set_missed_hours",
        description="Manager: Manually edit or correct a housemate's missed chore hours",
    )
    @app_commands.describe(
        member="Discord member whose hours to adjust",
        hours="New missed chore debt hours (e.g. 0 to clear, or specific number)",
        reason="Optional reason for the adjustment",
    )
    @has_manager_role()
    async def set_missed_hours(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        hours: int,
        reason: str = "Manager manual correction",
    ):
        target_hours = max(0, hours)
        user = await self.bot.db.get_user(member.id)
        if not user:
            name_parts = member.display_name.split()
            f_name = name_parts[0] if name_parts else member.name
            l_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""
            await self.bot.db.upsert_user(member.id, f_name, l_name, target_hours)
            old_hours = 0
        else:
            old_hours = user["missed_chore_hours"]
            await self.bot.db.set_user_missed_hours(member.id, target_hours)

        embed = discord.Embed(
            title="⏱️ Missed Hours Updated",
            description=f"Successfully updated delinquent chore hours for {member.mention}.",
            color=discord.Color.gold(),
            timestamp=datetime.utcnow(),
        )
        embed.add_field(name="Previous Hours", value=f"`{old_hours} hrs`", inline=True)
        embed.add_field(name="New Hours", value=f"`{target_hours} hrs`", inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.set_footer(text=f"Adjusted by {interaction.user.display_name}")

        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(UsersCog(bot))