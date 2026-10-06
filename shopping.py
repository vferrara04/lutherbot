import discord

async def get_target_channel(client, channel_id):
    """Utility helper to fetch or get cached channel safely."""
    channel = client.get_channel(channel_id)
    if channel is None:
        try:
            channel = await client.fetch_channel(channel_id)
        except (discord.NotFound, discord.HTTPException):
            return None
    return channel

async def make_shopping_list(msg, client, channel_id, check):
    requests = []
    async for request in msg.channel.history(limit=2000, before=msg):
        # scans messages until previous list request
        if request.content.startswith('!shopping'):
            break
        if request.content.startswith('!'):
            for line in request.content.splitlines():
                requests.append(line.strip('! '))
    
    fs_dm = await get_target_channel(client, channel_id)
    if not fs_dm:
        return

    # generates alphabetized shopping list in private channel
    # adds a reaction to each item to act as a check off button
    for request in sorted(requests):
        if request:
            mymsg = await fs_dm.send(request)
            await mymsg.add_reaction(check)
        
    copypaste = '' # single copy-pasteable message
    for request in sorted(set(requests)):
        if len(copypaste) > 1950: # if message approaches discord char limit
            await fs_dm.send(copypaste)
            copypaste = ''

        copypaste = copypaste + request + '\n'
    
    if copypaste.strip():
        await fs_dm.send(copypaste)

async def delete_item(payload, client, channel_id):
    try:
        user = await client.fetch_user(payload.user_id)
    except discord.NotFound:
        return
    
    if not user.bot:
        fs_dm = await get_target_channel(client, channel_id)
        if not fs_dm:
            return
        
        try:
            message = await fs_dm.fetch_message(payload.message_id)
        except discord.NotFound:
            return

        if message.author.bot:
            await message.delete()async def make_shopping_list(msg, client, id, check):
    requests = []
    async for request in msg.channel.history(limit = 2000, before = msg):
        # scans messages until previous list request
        if request.content.startswith('!shopping'):
            break
        if request.content.startswith('!'):
            for line in request.content.splitlines():
                requests.append(line.strip('! '))
    
    fs_dm = client.get_channel(id)    

    # generates alphabetized shopping list in private channel
    # adds a reaction to each item to act as a check off button
    for request in sorted(requests):
        if request:
            mymsg = await fs_dm.send(request)
            await mymsg.add_reaction(check)
        
    copypaste = '' # also sends a single copy-pasteable message for this who prefer not to use this
    for request in sorted(set(requests)):
        if len(copypaste) > 1950: # if message approches discord char limit
            await fs_dm.send(copypaste)
            copypaste = ''

        copypaste = copypaste + request + '\n'
    
    await fs_dm.send(copypaste)

async def delete_item(payload, client, id):
    user = await client.fetch_user(payload.user_id)
    
    if not user.bot:
        fs_dm = client.get_channel(id)
        message = await fs_dm.fetch_message(payload.message_id)
        
        if message.author.bot:
            await fs_dm.delete_messages([message])
