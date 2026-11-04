# 🧹 LutherBot

**LutherBot** is an asynchronous, interactive Discord bot built with `discord.py` and `aiosqlite` designed for co-ops, shared houses, and student living communities. It automates weekly chore scheduling, photo-proof submission tickets, delinquent hour tracking, makeup chore bounties, and communal shopping lists through persistent Discord UI dashboards.

## ✨ Features

* **🛠️ Master Chore Templates:** Define standardized house chores with descriptions, credit hours, and due days.
* **📋 Weekly Assignments & Rollover:** Automatically assign chores each ISO week (`YYYY-Www`) from recurring templates. Rolling over a week automatically converts unfinished chores into delinquent debt hours for responsible members and provisions the next week's schedule.
* **📸 Ticket-Based Proof Submissions:** Housemates submit chore proof via `/chore_submit`, which spawns dedicated review threads (supporting both solo and partner/shared submissions) where managers can approve or reject tasks with a single click.
* **🧹 Makeup Bounty Board:** Managers can post available makeup chores. Housemates with missed chore hours can claim bounties from a live, persistent board and submit photo proof to work off their debt.
* **🛒 Communal Shopping List:** Track needed house supplies and food requests, claim items to purchase, and log receipts/costs.
* **🎛️ Persistent Interactive Dashboards:** Built with `discord.ui.View` (with `timeout=None`), allowing buttons and paginated dropdown menus to survive bot restarts without losing state.

## 📂 Project Architecture

```text
├── data/
│   └── tracker.db             # Auto-generated SQLite database
├── src/
│   └── lutherbot/
│       ├── __init__.py
│       ├── __main__.py        # Package entry point
│       ├── main.py            # Bot subclass, setup_hook, persistent views & cog loader
│       ├── config.py          # Environment variable configuration & paths
│       ├── database/
│       │   └── db.py          # Asynchronous SQLite wrapper (aiosqlite)
│       └── cogs/
│           ├── assignments.py # WeeklyAssignmentsView, rollover & debt modals
│           ├── chore_views.py # ChoreManagerView & PartnerPromptView
│           ├── chores.py      # Slash commands for chores & submissions
│           ├── helpers.py     # ISO week math, role checks, & Paginated UI base classes
│           ├── makeups.py     # Makeup Bounty views & commands
│           ├── modals.py      # UI Modals for adding/editing chores
│           ├── reviews.py     # ThreadReviewView & ticket thread spawning
│           ├── shopping.py    # Communal shopping list views & commands
│           └── users.py       # House roster management commands
├── .env                       # Environment variables (not committed)
├── pyproject.toml             # Project metadata, scripts & dependencies (uv_build)
├── uv.lock                    # Locked dependency graph managed by uv
└── README.md
```

## ⚙️ Prerequisites & Installation

### 1. Requirements

* **Python `>=3.14`**
* **[uv](https://docs.astral.sh/uv/)** (Fast Python package and project manager)
* A Discord Bot Application with **Server Members Intent** and **Message Content Intent** enabled in the [Discord Developer Portal](https://discord.com/developers/applications).

### 2. Install Dependencies with `uv`

Clone the repository and sync the locked virtual environment using `uv`:

```bash
git clone <your-repository-url>
cd lutherbot
uv sync
```

This automatically provisions a Python `>=3.14` virtual environment (`.venv`) and installs all exact dependencies from `uv.lock`:
* `discord-py>=2.3.0` (locked at `2.7.1`)
* `aiosqlite>=0.22.1`
* `python-dotenv>=1.2.4`

## 🔐 Configuration (`.env`)

Create a `.env` file in the project root directory and populate it with your Discord server's IDs:

```env
# Bot Credentials
DISCORD_TOKEN=your_discord_bot_token_here
GUILD_ID=123456789012345678

# Role IDs
WORM_ROLE_ID=123456789012345678       # Chore Manager / Admin Role ID
FOOD_ROLE_ID=123456789012345678       # Food / Steward Role ID

# Channel IDs
WORM_CHANNEL_ID=123456789012345678       # Manager dashboard channel
CHORE_CHANNEL_ID=123456789012345678      # Public chore announcements channel
MAKEUP_CHANNEL_ID=123456789012345678     # Public makeup bounty board channel
SUBMISSION_CHANNEL_ID=123456789012345678 # Channel where proof review threads spawn
FOOD_CHANNEL_ID=123456789012345678       # Shopping board channel
FOOD_REQUEST_CHANNEL_ID=123456789012345678
```

> **Note:** Setting `GUILD_ID` syncs slash commands instantaneously to your server on startup. If omitted (`0`), commands sync globally (which can take up to an hour on Discord's end).

## 🚀 Running the Bot

Because `lutherbot` defines a project script entry point (`lutherbot = "lutherbot:main"` in `pyproject.toml`), you can launch it directly with `uv`:

```bash
uv run lutherbot
```

Alternatively, you can run it as a Python module:

```bash
uv run python -m lutherbot
```

On startup, **LutherBot** will automatically:

1. Create the `data/` directory and initialize the SQLite schema in `data/tracker.db`.
2. Re-register persistent UI views (`ThreadReviewView`, `MakeupBoardView`, `ShoppingBoardView`, `ChoreManagerView`, `WeeklyAssignmentsView`).
3. Load all feature extensions (`users`, `chores`, `makeups`, `shopping`).
4. Synchronize application slash commands with Discord.

## 📖 Slash Commands Reference

### 👤 Member Commands

| Command | Description |
| :--- | :--- |
| `/my_chores` | View your active weekly chore assignments and current missed chore hour debt. |
| `/chore_submit` | Open a submission thread (or jump to an existing one) to upload photo proof for an assigned chore or claimed makeup bounty. Supports submitting solo or jointly with a chore partner. |

### 🛡️ Manager Commands (`WORM_ROLE_ID` or Administrator)

| Command | Description |
| :--- | :--- |
| `/chore_manager` | Posts the interactive **Master Chore Templates Manager** dashboard to the manager channel. |
| `/assignments_dashboard` | Posts the **House Chore Assignments** dashboard to reassign tasks, force-approve statuses, edit member debt hours, or trigger rollovers. |
| `/week_rollover [old_week] [new_week]` | Finalizes the departing week (converting uncompleted tasks into missed debt hours) and provisions assignments for the new week. |
| `/pending_reviews` | Displays a queue and direct jump links for all active submission threads awaiting manager approval. |
| `/chore_add` | Quickly create a new master chore template via slash command parameters. |
| `/chore_edit <chore_id>` | Opens an interactive modal to edit a chore's title, description, hours, or due day. |
| `/chore_delete <chore_id>` | Permanently deletes a master chore template. |
| `/chore_assign <chore_id> <member>` | Assigns a chore to a member for a target week and optionally saves it as a recurring weekly template. |
| `/makeup_dashboard [week]` | Posts the interactive manager dashboard for creating, viewing, and deleting makeup bounties by week. |
| `/makeup_post_board` | Posts the public **Open Makeup Chore Bounties** board to `MAKEUP_CHANNEL_ID` for members to claim tasks. |
| `/makeup_add [chore] [week]` | Adds a master chore template into the available makeup bounty pool for a given week. |

## 🗄️ Database Schema Overview

LutherBot uses `aiosqlite` with foreign-key cascading and check constraints across six core tables in `data/tracker.db`:

* **`users`**: Stores Discord `uid`, `first_name`, `last_name`, and `missed_chore_hours`.
* **`chores`**: Stores master chore templates (`cid`, `title`, `description`, `hours`, `due_day`).
* **`chore_templates`**: Maps recurring `(cid, uid)` pairs used to populate new weeks during rollover.
* **`chore_assignments`**: Tracks weekly instances `(cid, uid, week)` with statuses (`pending`, `under_review`, `missed`, `rejected`, `approved`) and linked Discord `thread_id`.
* **`makeup_chores`**: Tracks bounty instances (`mid`, `cid`, `uid`, `status`, `thread_id`, `week`). Approving a makeup chore automatically deducts the chore's credit hours from the user's `missed_chore_hours`.
* **`shopping_items`**: Tracks communal shopping requests (`id`, `item_name`, `quantity`, `requested_by`, `claimed_by`, `cost`, `status`).

## 👤 Author

* **Vincent Ferrara** — [vferrara@umich.edu](mailto:vferrara@umich.edu)