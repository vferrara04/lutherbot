# src/lutherbot/cogs/users.py
from datetime import datetime
import discord
from discord import app_commands
from discord.ext import commands
from lutherbot.cogs.helpers import (
    has_manager_role,
    ensure_user_registered,
    PaginatedDashboardView,
)


class RosterPaginationView(PaginatedDashboardView):
    """Paginates the /roster table if there are more than 40 members."""

    def __init__(self, members: list):
        super().__init__(bot=None, per_page=40, manager_only=False, timeout=120)
        self.members = members

    async def build_embed(self, interaction: discord.Interaction | None = None) -> discord.Embed:
        return self.build_roster_embed()

    def build_roster_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🏠 House Co-op Roster",
            color=discord.Color.dark_theme(),
            timestamp=datetime.utcnow(),
        )
        chunk, total_pages = self.paginate(self.members)
        if not self.members:
            embed.description = "No members registered yet. Use `/register` to sign up!"
            return embed

        lines = [
            f"{'Member':<18} | {'Debt':<6} | {'Discord ID':<18}",
            "-" * 48,
        ]

        for m in chunk:
            full_name = f"{m['first_name']} {m['last_name']}"[:17]
            debt = f"{m['missed_chore_hours']}h"
            lines.append(f"{full_name:<18} | {debt:<6} | {str(m['uid']):<18}")

        embed.description = (
            f"```text\n{chr(10).join(lines)}\n```\n"
            f"*Page {self.page + 1}/{total_pages} • Total registered: {len(self.members)}*"
        )
        return embed

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._turn_page(interaction, -1)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._turn_page(interaction, 1)


class UsersCog(commands.Cog):
    """Cog for managing house member registration and roster."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _register_member(
        self,
        member: discord.Member | discord.User,
        first_name: str,
        last_name: str,
        debt_hours: int | None = None,
    ) -> tuple[str, str, int] | None:
        first_clean = first_name.strip().title()
        last_clean = last_name.strip().title()
        if not first_clean or not last_clean:
            return None

        if debt_hours is None:
            existing = await self.bot.db.get_user(member.id)
            debt = existing["missed_chore_hours"] if existing else 0
        else:
            debt = max(0, debt_hours)

        await self.bot.db.upsert_user(
            user_id=member.id,
            first_name=first_clean,
            last_name=last_clean,
            missed_chore_hours=debt,
        )
        return first_clean, last_clean, debt

    @app_commands.command(
        name="register",
        description="Register yourself in the house chore roster",
    )
    @app_commands.describe(
        first_name="Your real first name",
        last_name="Your real last name",
    )
    async def register(self, interaction: discord.Interaction, first_name: str, last_name: str):
        res = await self._register_member(interaction.user, first_name, last_name)
        if not res:
            await interaction.response.send_message(
                "❌ Please provide both a valid first and last name.", ephemeral=True
            )
            return

        first_clean, last_clean, current_debt = res
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
        embed.add_field(name="Missed Debt Hours", value=f"`{current_debt} hrs`", inline=True)
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
        res = await self._register_member(member, first_name, last_name, initial_debt_hours)
        if not res:
            await interaction.response.send_message(
                "❌ First name and last name cannot be empty.", ephemeral=True
            )
            return

        first_clean, last_clean, debt = res
        embed = discord.Embed(
            title="👤 Housemate Added to Roster",
            description=f"Successfully registered **{first_clean} {last_clean}**.",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow(),
        )
        embed.add_field(name="Member", value=f"{member.mention} (`{member.id}`)", inline=True)
        embed.add_field(name="Starting Debt", value=f"`{debt} hrs`", inline=True)
        embed.set_footer(text=f"Added by {interaction.user.display_name}")

        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="roster",
        description="View all registered housemates and their debt hours",
    )
    @has_manager_role()
    async def roster(self, interaction: discord.Interaction):
        members = await self.bot.db.get_all_users()
        view = RosterPaginationView(members)
        embed = view.build_roster_embed()

        if len(members) > view.per_page:
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
        user = await ensure_user_registered(self.bot.db, member, default_debt=0)
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