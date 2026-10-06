import gspread
import json
import datetime
import time
import os
import discord
import config

CHORE_CHANNEL = 1100529167201734657

NUMBER_EMOJIS = {'1️⃣': 1, '2️⃣': 2, '3️⃣': 3, '4️⃣': 4, '5️⃣': 5, '6️⃣': 6}

weekdays = {
    "Thursday": 3,
    "Friday": 4,
    "Saturday": 5,
    "Sunday": 6,
    "Monday": 0,
    "Tuesday": 1,
    "Wednesday": 2
}

async def get_target_channel(client, channel_id):
    channel = client.get_channel(channel_id)
    if channel is None:
        try:
            channel = await client.fetch_channel(channel_id)
        except (discord.NotFound, discord.HTTPException):
            return None
    return channel

def sheets_init(doc_name, sheet_name):
    gc = gspread.service_account(filename='creds.json')
    sh = gc.open(doc_name)
    if sheet_name:
        sh = sh.worksheet(sheet_name)
    return sh

def get_schedule():
    template = sheets_init(config.SCHEDULE, 'Schedule by Day')
    schedule = {}

    for column in range(1, 9):
        col = template.col_values(column)
        if not col:
            continue
        day, col_cells = col[0], col[1:]
        currentchore = ''

        for cell in col_cells:
            if cell and cell[-1].isnumeric():
                cell = cell.replace('\n', ' ')
                if ',' in cell:
                    currentchore, _ = cell.rsplit(',', 1)
                else:
                    currentchore = cell
                currentchore = currentchore.strip()
                if column < 8:
                    currentchore = f'{day} {currentchore}'

            elif cell and cell != 'Makeup':
                cell = cell.strip()
                if cell not in schedule:
                    schedule[cell] = [currentchore]
                elif currentchore not in schedule[cell]:
                    schedule[cell].append(currentchore)

    with open('schedule.json', 'w') as file:
        json.dump(schedule, file, indent=2)

async def submit_chore(msg):
    if not os.path.exists('schedule.json'):
        await msg.reply("Schedule data not found. Please run `/update` or `!update` first.")
        return

    with open('schedule.json', 'r') as file:
        schedule = json.load(file)

    name = config.USERNAMES.get(msg.author.name)
    if not name:
        await msg.reply(f"User `{msg.author.name}` not found in `config.USERNAMES`.")
        return

    if name not in schedule or not schedule[name]:
        await msg.reply(f"No chores assigned to {name}.")
        return

    choices = f'{name}, which chore are you submitting?'
    for index, chore in enumerate(schedule[name], start=1):
        choices += f'\n{index}: {chore}'

    mymsg = await msg.reply(choices)
    for emoji, num in NUMBER_EMOJIS.items():
        if num <= len(schedule[name]):
            await mymsg.add_reaction(emoji)

async def prepare_confirm(payload, client):
    channel = await get_target_channel(client, CHORE_CHANNEL)
    if not channel:
        return
        
    try:
        msg = await channel.fetch_message(payload.message_id)
    except discord.NotFound:
        return

    lines = msg.content.split('\n')
    header = lines[0]
    name = header.split(',')[0].strip()

    index = NUMBER_EMOJIS.get(str(payload.emoji))
    if not index or index >= len(lines):
        return

    chore_line = lines[index]
    chore = chore_line.split(':', 1)[1].strip() if ':' in chore_line else chore_line.strip()
    msg = await msg.edit(content=f'{name}, {chore}')

    names = []
    if os.path.exists('schedule.json'):
        with open('schedule.json', 'r') as file:
            schedule = json.load(file)
        for person, person_chores in schedule.items():
            if chore in person_chores and person not in [name, 'Makeup', 'Ian Beck...?']:
                names.append(person)
    
    await msg.clear_reactions()
    await msg.add_reaction('✅')
    for person in names:
        mymsg = await msg.reply(f'Also submitting for {person}?')
        await mymsg.add_reaction('✅')
        await mymsg.add_reaction('❌')

    await msg.channel.send('Slay')

async def confirm_teammate(msg, client):
    channel = await get_target_channel(client, msg.reference.channel_id)
    if not channel:
        return
        
    choremsg = await channel.fetch_message(msg.reference.message_id)
    name = msg.content.removeprefix('Also submitting for ').strip('?')
    await choremsg.edit(content=f'{name}, {choremsg.content}')
    await msg.delete()

async def confirm_chore(payload, client):
    channel = await get_target_channel(client, CHORE_CHANNEL)
    if not channel:
        return

    wholemsg = await channel.fetch_message(payload.message_id)
    msg = [word.strip() for word in wholemsg.content.split(',')]
    if len(msg) < 2:
        return

    names, chore = msg[:-1], msg[-1]

    choreday = chore.split(' ')[0].strip(',')
    if choreday in weekdays:
        chore = chore[chore.find(' ') + 1:]
    else:
        choreday = ''

    submit_date = wholemsg.created_at - datetime.timedelta(hours=5)
    monday_offset = submit_date.weekday()
    
    if choreday and monday_offset < weekdays[choreday]:
        monday_offset += 7

    last_monday = submit_date - datetime.timedelta(days=monday_offset)
    last_monday_str = last_monday.strftime("%m/%d/%Y")

    sheet_name = f'Week of {last_monday_str}'
    sh = sheets_init(config.SCHEDULE, '')
    try:
        thisweek = sh.worksheet(sheet_name)
    except gspread.WorksheetNotFound:
        template = sh.worksheet('Schedule by Day')
        template.duplicate(new_sheet_name=sheet_name)
        thisweek = sh.worksheet(sheet_name)

    column = 8
    found = False
    if choreday:
        column = weekdays[choreday] + 1

    for _ in range(2):
        if found:
            break
        col = thisweek.col_values(column)[1:]
        row = 2
        for cell in col:
            if found:
                if cell.strip() in names:
                    coord = chr(column + 64) + str(row)
                    thisweek.format(f'{coord}:{coord}', {
                        'backgroundColor': {
                            'red': 0.8509803921568627,
                            'green': 0.9176470588235294,
                            'blue': 0.8274509803921568
                        }
                    })
                    names.remove(cell.strip())
                    if not names:
                        break
            if cell.replace('\n', ' ').startswith(chore):
                found = True
            row += 1
        column = 9

def generate_missed_chores():
    chorelist = sheets_init(config.TRACKER, config.CHORE_LIST)
    chores_col = chorelist.col_values(1)
    chore_hours = chorelist.col_values(2)
    weeks_missed = chorelist.col_values(3)

    values = list(zip(chores_col, chore_hours, weeks_missed))[1:]
    missed_chore_list = {}

    for row in values:
        try:
            weeks = int(row[2])
        except ValueError:
            continue

        if weeks > 0:
            parts = row[0].split(',')
            if len(parts) < 2:
                continue
            name, chore = parts[0].strip(), parts[1].strip()
            hours = row[1]

            if weeks > 1:
                chore = f'{chore}, {hours} weeks in a row'
            if name in missed_chore_list:
                missed_chore_list[name].append(chore)
            else:
                missed_chore_list[name] = [chore]
    print(missed_chore_list)
