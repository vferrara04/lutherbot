import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

GUILD_ID = int(os.getenv("GUILD_ID", 0))

WORM_CHANNEL_ID = int(os.getenv("WORM_CHANNEL_ID", 0))

CHORE_CHANNEL_ID = int(os.getenv("CHORE_CHANNEL_ID", 0))

WORM_ROLE_ID = int(os.getenv("MANAGER_ROLE_ID", 0))

FOOD_ROLE_ID = int(os.getenv("FOOD_ROLE_ID", 0))

FOOD_CHANNEL_ID = int(os.getenv("FOOD_CHANNEL_ID", 0))

FOOD_REQUEST_CHANNEL_ID = int(os.getenv("FOOD_REQUEST_CHANNEL_ID", 0))

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DATABASE_PATH = DATA_DIR / "tracker.db"

DATA_DIR.mkdir(parents=True, exist_ok=True)