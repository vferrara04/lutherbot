import random

async def send_rat(msg):
    pic = random.choice(
        [
            'https://www.peta.org/wp-content/uploads/2015/04/10903825_872344489483233_7702124773103899276_o-668x336.jpg?20190103121630',
            'https://imgur.com/r7WkJOX',
            'https://media.istockphoto.com/id/1197373509/photo/a-grey-pet-rat-sits-on-a-toy-motorcycle.jpg?s=170667a&w=0&k=20&c=wHXqWJ5NB4TmNbzwYm9KclN8gcsSRIWBJlfwGk0jehY=',
        ]
        
    )
    await msg.channel.send(pic)

async def emo(msg):
    if not msg.author.bot and msg.channel.name != 'makeup-chores':
        if msg.author.name != 'taztaztaz': # he got annoyed
            #await msg.channel.send('"Real Emo" only consists of the dc Emotional Hardcore scene and the late 90\'s Screamo scene. What is known by "Midwest Emo" is nothing but Alternative Rock with questionable real emo influence. When people try to argue that bands like My Chemical Romance are not real emo, while saying that Sunny Day Real Estate is, I can\'t help not to cringe because they are just as fake emo as My Chemical Romance (plus the pretentiousness). Real emo sounds ENERGETIC, POWERFUL and somewhat HATEFUL. Fake emo is weak, self pity and a failed attempt to direct energy and emotion into music. Some examples of REAL EMO are Pg 99, Rites of Spring, Cap n Jazz (the only real emo band from the midwest scene) and Loma Prieta. Some examples of FAKE EMO are American Football, My Chemical Romance and Mineral EMO BELONGS TO HARDCORE NOT TO INDIE, POP PUNK, ALT ROCK OR ANY OTHER MAINSTREAM GENRE')
            await msg.channel.send("https://imgur.com/sAEplrx")

async def shut_up(msg):
    async for spam in msg.channel.history(limit = 5, before = msg):
        spam_array = []
        if spam.author.bot:
            spam_array.append(spam)
        await msg.channel.delete_messages(spam_array)