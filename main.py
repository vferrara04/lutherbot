import os
import discord
from discord import app_commands
from dotenv import load_dotenv
import shopping
import misc
import makeups
import chores

GREEN_CHECK = '\U00002705'
SHOPPING_ID = 1110021975109288006
MAKEUP_ID = 1115356156307718144
SERVER_ID = 1100528927803461634
WORM = 1103462042490384434
PREZ = 1103461097803092079
FOOD_STEWARD = 1103461475152039956

load_dotenv()
token = os.getenv('token') or os.getenv('TOKEN')
client = discord.Client(intents=discord.Intents.all())
tree = app_commands.CommandTree(client)

@client.event
async def on_ready():
    await tree.sync(guild=discord.Object(id=SERVER_ID))
    print(f'{client.user} has connected to Discord!')

@tree.command(
    name="update",
    description="Updates the stored list of chores",
    guild=discord.Object(id=SERVER_ID)
)
async def update_schedule(interaction):
    await interaction.response.defer()
    chores.get_schedule()
    await interaction.followup.send("Schedule updated!")

@tree.command(
    name="missedchores",
    description="Generates the list of chores missed this week",
    guild=discord.Object(id=SERVER_ID)
)
async def missed_chores_command(interaction):
    await interaction.response.defer()
    chores.generate_missed_chores()
    await interaction.followup.send("Generated missed chores!")

@client.event
async def on_message(msg):
    if msg.author == client.user:
        return

    channel_name = getattr(msg.channel, 'name', None)
    is_member = isinstance(msg.author, discord.Member)

    if channel_name == 'food-requests':
        has_food_role = is_member and msg.author.get_role(FOOD_STEWARD)
        if msg.content.startswith('!shopping') and (has_food_role or msg.author.name == 'failedcorporatecumslut'):
            await shopping.make_shopping_list(msg, client, SHOPPING_ID, GREEN_CHECK)

    elif channel_name == 'makeup-opportunities':
        if is_member and msg.author.get_role(WORM):
            await makeups.create_makeup(msg, GREEN_CHECK)

    elif channel_name == 'chore-submissions' and not msg.author.bot:
        if msg.attachments:
            await chores.submit_chore(msg)
        
        if msg.content.startswith('!update') and is_member and msg.author.get_role(WORM):
            chores.get_schedule()

    if 'emo' in msg.content.lower():
        await misc.emo(msg)

    if 'rat' in msg.content.lower() and not msg.author.bot:
        await misc.send_rat(msg)

    if msg.author.name == 'vivcifi' and msg.content.lower() == 'shut up':
        await misc.shut_up(msg)
                
    if msg.content.lower() == 'what':
        await msg.channel.send('chicken butt')

    if msg.author.name in ['emma0022_', 'brandon23669']:
        await msg.channel.send('meow')

    if msg.author.name in ['woba6y4748', 'adam055593']:
        await msg.channel.send('cowabunga')

@client.event
async def on_raw_reaction_add(payload):
    if payload.channel_id == SHOPPING_ID:
        await shopping.delete_item(payload, client, SHOPPING_ID)
                
    elif payload.channel_id == MAKEUP_ID:
        await makeups.claim_makeup(payload, client, SERVER_ID, MAKEUP_ID, WORM)

    elif payload.channel_id == chores.CHORE_CHANNEL:
        try:
            server = await client.fetch_guild(SERVER_ID)
            user = await server.fetch_member(payload.user_id)
        except discord.NotFound:
            return

        if not user.bot:
            channel = client.get_channel(chores.CHORE_CHANNEL) or await client.fetch_channel(chores.CHORE_CHANNEL)
            try:
                msg = await channel.fetch_message(payload.message_id)
            except discord.NotFound:
                return

            if msg.content.startswith('Also submitting for '):
                if str(payload.emoji) == '✅':
                    await chores.confirm_teammate(msg, client)
                elif str(payload.emoji) == '❌':
                    await msg.delete()

            elif str(payload.emoji) == '✅' and user.get_role(WORM):
                await chores.confirm_chore(payload, client)
            elif str(payload.emoji) in chores.NUMBER_EMOJIS:
                await chores.prepare_confirm(payload, client)

if __name__ == '__main__':
    client.run(token)
