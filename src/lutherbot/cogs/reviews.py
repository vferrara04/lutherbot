# src/lutherbot/cogs/reviews.py
from datetime import datetime
import discord
from lutherbot import config
from lutherbot.cogs.helpers import check_is_manager


class ThreadReviewView(discord.ui.View):
    """Attached to submission threads. timeout=None allows buttons to work after bot restarts."""

    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not check_is_manager(interaction.user, interaction.guild):
            await interaction.response.send_message(
                "⛔ **Restricted**: Only members with the **Manager** role can approve or reject chore submissions.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(
        label="Approve",
        style=discord.ButtonStyle.success,
        emoji="✅",
        custom_id="chore_review_approve",
    )
    async def approve(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not check_is_manager(interaction.user, interaction.guild):
            await interaction.response.send_message(
                "⛔ **Restricted**: Only members with the **Manager** role can approve chore submissions.",
                ephemeral=True,
            )
            return

        thread = interaction.channel
        db = interaction.client.db

        assignments = await db.get_assignment_by_thread(thread.id)
        if not assignments:
            await interaction.response.send_message(
                "❌ No active assignment linked to this thread.", ephemeral=True
            )
            return

        await db.update_status_by_thread(thread.id, "approved")

        for row in assignments:
            if row["chore_type"] == "makeup" and row["mid"] is not None:
                await db.resolve_missed_chores(row["mid"], row["uid"])

        for child in self.children:
            child.disabled = True

        embed = interaction.message.embeds[0]
        embed.color = discord.Color.green()
        embed.title = "✅ Approved"
        embed.set_footer(
            text=f"Approved by {interaction.user.display_name} • {datetime.now().strftime('%b %d, %H:%M')}"
        )

        await interaction.response.edit_message(embed=embed, view=self)
        await thread.send(
            "🎉 **Submission approved!** Archiving and locking ticket..."
        )
        await thread.edit(locked=True, archived=True)

    @discord.ui.button(
        label="Reject",
        style=discord.ButtonStyle.danger,
        emoji="❌",
        custom_id="chore_review_reject",
    )
    async def reject(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not check_is_manager(interaction.user, interaction.guild):
            await interaction.response.send_message(
                "⛔ **Restricted**: Only members with the **Manager** role can reject chore submissions.",
                ephemeral=True,
            )
            return

        thread = interaction.channel
        db = interaction.client.db

        assignments = await db.get_assignment_by_thread(thread.id)
        if not assignments:
            await interaction.response.send_message(
                "❌ No assignment found.", ephemeral=True
            )
            return

        await db.update_status_by_thread(thread.id, "rejected")

        for child in self.children:
            child.disabled = True

        embed = interaction.message.embeds[0]
        embed.color = discord.Color.red()
        embed.title = "❌ Rejected - Changes Required"
        embed.set_footer(
            text=f"Rejected by {interaction.user.display_name} • {datetime.now().strftime('%b %d, %H:%M')}"
        )

        await interaction.response.edit_message(embed=embed, view=self)

        mentions = " ".join(f"<@{row['uid']}>" for row in assignments)
        await thread.send(
            f"⚠️ {mentions} Your proof was rejected. Please review manager feedback, redo the task, and upload new photos here."
        )

async def spawn_review_thread(
    interaction: discord.Interaction,
    thread_title: str,
    content: str,
    embed: discord.Embed,
    view: discord.ui.View,
) -> tuple[discord.Thread | None, str | None]:
    channel_id = int(config.SUBMISSION_CHANNEL_ID)
    channel = interaction.client.get_channel(channel_id) or await interaction.client.fetch_channel(channel_id)

    if isinstance(channel, discord.ForumChannel):
        post = await channel.create_thread(
            name=thread_title[:100],
            content=content,
            embed=embed,
            view=view,
        )
        return post.thread, None

    # TextChannel fallback
    thread = await channel.create_thread(
        name=thread_title[:100],
        type=discord.ChannelType.public_thread,
    )
    await thread.send(content=content, embed=embed, view=view)
    return thread, None