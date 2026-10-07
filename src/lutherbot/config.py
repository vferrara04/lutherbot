import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
BOT_TOKEN = TOKEN  # Alias so both config.TOKEN and config.BOT_TOKEN work

GUILD_ID = int(os.getenv("GUILD_ID", 0))

WORM_CHANNEL_ID = int(os.getenv("WORM_CHANNEL_ID", 0))
CHORE_CHANNEL_ID = int(os.getenv("CHORE_CHANNEL_ID", 0))
MAKEUP_CHANNEL_ID = int(os.getenv("MAKEUP_CHANNEL_ID", 0))
SUBMISSION_CHANNEL_ID = int(os.getenv("SUBMISSION_CHANNEL_ID", 0))

WORM_ROLE_ID = int(os.getenv("WORM_ROLE_ID", 0))
MANAGER_ROLE_ID = WORM_ROLE_ID

FOOD_ROLE_ID = int(os.getenv("FOOD_ROLE_ID", 0))
FOOD_CHANNEL_ID = int(os.getenv("FOOD_CHANNEL_ID", 0))
FOOD_REQUEST_CHANNEL_ID = int(os.getenv("FOOD_REQUEST_CHANNEL_ID", 0))

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DATABASE_PATH = DATA_DIR / "tracker.db"

DATA_DIR.mkdir(parents=True, exist_ok=True)