import discord

async def get_target_channel(client, channel_id):
    channel = client.get_channel(channel_id)
    if channel is None:
        try:
            channel = await client.fetch_channel(channel_id)
        except (discord.NotFound, discord.HTTPException):
            return None
    return channel

async def create_makeup(msg, check):
    if msg.content.startswith('!makeup'):
        opportunity = msg.content.removeprefix('!makeup ').strip()
        opportunity = opportunity + '\nClick the check mark to claim this chore!'
        await msg.delete()
        new_msg = await msg.channel.send(opportunity)
        await new_msg.add_reaction(check)

async def claim_makeup(payload, client, serve, makeup, worm):
    try:
        server = await client.fetch_guild(serve)
        user = await server.fetch_member(payload.user_id)
    except discord.NotFound:
        return
    
    if not user.bot:
        channel = await get_target_channel(client, makeup)
        if not channel:
            return

        try:
            msg = await channel.fetch_message(payload.message_id)
        except discord.NotFound:
            return

        if 'claimed' in msg.content:
            return
        
        if msg.author.bot:
            text = msg.content
            await msg.delete()

            if not user.get_role(worm):
                text = text.removesuffix('\nClick the check mark to claim this chore!')
                text = f'{text}\n{user.display_name} claimed this chore!'
                await channel.send(text)
