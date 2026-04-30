# 🤖 Telegram Content Bot

A Telegram bot that lets users unlock and receive content files by plan, with admin controls, QR payment, force subscribe, and broadcasting.

---

## 📁 File Structure

```
tgbot/
├── main.py           # Main bot logic
├── database.py       # MongoDB connection
├── requirements.txt  # Python dependencies
├── Procfile          # For Koyeb / Heroku deployment
├── .env.example      # Environment variable template
├── .gitignore        # Keeps secrets out of GitHub
└── README.md         # This file
```

---

## ⚙️ Setup Guide

### Step 1 — Get your credentials

| What | Where to get it |
|------|----------------|
| `API_ID` & `API_HASH` | https://my.telegram.org → My Applications |
| `BOT_TOKEN` | @BotFather on Telegram → /newbot |
| `MONGO_URI` | https://mongodb.com/atlas → Free cluster → Connect |

---

### Step 2 — Fill in your values

Open `main.py` and update these 3 lines:

```python
API_ID    = int(os.environ.get("API_ID",    "YOUR_API_ID"))
API_HASH  = os.environ.get("API_HASH",  "YOUR_API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN")
```

Open `database.py` and update:

```python
MONGO_URI = os.environ.get("MONGO_URI", "YOUR_MONGO_URI")
```

> **Tip:** On Koyeb/Railway, set these as Environment Variables instead of editing the files directly. That way your secrets stay safe.

---

### Step 3 — Install dependencies

```bash
pip install -r requirements.txt
```

---

### Step 4 — Run the bot

```bash
python main.py
```

---

### Step 5 — First time setup

Send these commands to your bot on Telegram:

```
/init       → Creates the database structure
/admin      → Opens the admin panel
```

---

## 🔑 Admin Commands

| Command | What it does |
|---------|-------------|
| `/admin` | Open admin control panel |
| `/init` | Initialise the database (run once) |
| `/stats` | Show user count and file counts |
| `/index 1` | Reply to a file + run this to save it to Plan 1 (use 1–4) |

---

## 📋 Admin Panel Features

- **Manage Plans (1–4)** — Edit description, price, add/clear unlock codes
- **Stats & Contents** — Total users, file count per plan
- **Broadcast** — Send text or photo to all users
- **Settings** — Upload QR code image, set force-subscribe channel

---

## 👤 User Flow

1. User sends `/start`
2. Bot checks if user has joined the required channel (Force Subscribe)
3. User picks a plan → sees description and price
4. User taps **Pay Now** → sees QR code to scan and pay
5. User taps **Unlock** → sends the code they received after payment
6. Bot validates the code and sends all files for that plan

---

## ☁️ Deploy on Koyeb (Free)

1. Push this repo to GitHub
2. Go to https://koyeb.com → New App → GitHub
3. Select your repo
4. Set environment variables:
   - `API_ID`
   - `API_HASH`
   - `BOT_TOKEN`
   - `MONGO_URI`
5. Set the run command to: `python main.py`
6. Deploy!

The built-in web server on port 8000 will keep the bot alive 24/7.

---

## 🛡️ Security Notes

- Admin is **hardcoded** to Telegram ID `7207674086` — only you can use admin commands
- Never commit your `.env` or real credentials to GitHub
- Use `.env.example` as a template, never the real `.env`
