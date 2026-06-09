# Deploying the Telegram Bot (Private MVP)

This runbook covers setting up and running the Telegram bot as a private
research assistant on a shared Hetzner server (`avtoqyzmet.kz`).

The API remains bound to localhost throughout the MVP phase — only the
Telegram long-polling bot is exposed to the network.

## Current Production Status

Deployed successfully on the existing Hetzner server for `avtoqyzmet.kz` on
2026-06-10 Asia/Almaty time.

- Host alias: `avto`.
- App user: `stockbot`.
- App root: `/home/stockbot/stock-ai-assistant`.
- Systemd service: `stockbot-telegram.service`.
- Bot: `@StockQ1AssistantBot`.
- Verification passed: Telegram live check returned `ok`, `stockbot-telegram`
  was `active` and `enabled`, logs showed `telegram_bot_started`, server
  `compileall` passed on Python 3.11, and `avtoqyzmet.kz` still returned
  `HTTP/2 200` through nginx.
- Delivery method used for this deployment: `rsync` into the separate
  `/home/stockbot/stock-ai-assistant` tree. Nginx and `/app/frontend-quasar`
  were not changed.

---

## Prerequisites

- A Linux server (Debian/Ubuntu recommended).
- Python 3.11+ installed.
- A Telegram bot token from [@BotFather](https://t.me/BotFather).
- A `.env` file on the server (never commit it).

---

## Server Setup

```bash
# Create the app user (no sudo)
sudo useradd -m -s /bin/bash stockbot

# Install system deps
sudo apt update && sudo apt install -y python3 python3-venv git

# Clone the repo
sudo -u stockbot git clone https://github.com/YOUR_USER/stock-ai-assistant.git \
  /home/stockbot/stock-ai-assistant

# Create .env
sudo -u stockbot vim /home/stockbot/stock-ai-assistant/.env
```

### Minimal `.env`

```ini
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_ENABLED=1
TELEGRAM_ALLOWED_CHAT_IDS=
FRED_API_KEY=optional_fred_key
ALPHA_VANTAGE_API_KEY=optional_av_key
FINNHUB_API_KEY=optional_finnhub_key
ALLOW_REMOTE_API=0
```

Only `TELEGRAM_BOT_TOKEN` and `TELEGRAM_ENABLED` are required for the bot
to start. All other keys are optional and control specific data sources.
Set `TELEGRAM_ALLOWED_CHAT_IDS` only after replacing it with real chat IDs;
do not leave placeholder values in production.

---

## Installing Dependencies

```bash
cd /home/stockbot/stock-ai-assistant
sudo -u stockbot python3 -m venv .venv
sudo -u stockbot .venv/bin/pip install -r requirements.txt
```

---

## Systemd Service

Create `/etc/systemd/system/stockbot-telegram.service`:

```ini
[Unit]
Description=Stock AI Assistant Telegram Bot
After=network.target

[Service]
Type=simple
User=stockbot
WorkingDirectory=/home/stockbot/stock-ai-assistant
EnvironmentFile=/home/stockbot/stock-ai-assistant/.env
ExecStart=/home/stockbot/stock-ai-assistant/.venv/bin/python \
  /home/stockbot/stock-ai-assistant/scripts/run_telegram_bot.py
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now stockbot-telegram
sudo systemctl status stockbot-telegram
```

---

## Database

The SQLite database is created at:

```
/home/stockbot/stock-ai-assistant/stock_ai_assistant.db
```

**Backup** (cron daily):

```bash
0 2 * * * cp /home/stockbot/stock-ai-assistant/stock_ai_assistant.db \
  /home/stockbot/stock-ai-assistant/backups/stock_ai_assistant_$(date +\%Y\%m\%d).db
```

**Restore** (replace with a backup):

```bash
systemctl stop stockbot-telegram
cp /home/stockbot/stock-ai-assistant/backups/stock_ai_assistant_20260601.db \
  /home/stockbot/stock-ai-assistant/stock_ai_assistant.db
systemctl start stockbot-telegram
```

---

## Logs

```bash
# Follow live
journalctl -u stockbot-telegram -f

# Last 100 lines
journalctl -u stockbot-telegram -n 100 --no-pager

# Filter by date
journalctl -u stockbot-telegram --since "2026-06-07" --until "2026-06-08"
```

---

## Updating

```bash
cd /home/stockbot/stock-ai-assistant
sudo -u stockbot git pull
sudo -u stockbot .venv/bin/pip install -r requirements.txt
sudo systemctl restart stockbot-telegram
```

---

## Rollback

```bash
cd /home/stockbot/stock-ai-assistant
sudo -u stockbot git checkout <previous-commit>
sudo systemctl restart stockbot-telegram
```

---

## Checking the Bot

1. Open Telegram and find your bot by its username.
2. Send `/start` — you should see the welcome message.
3. Send `/status` — the bot should respond with subscription state.
4. Send `/analyze AAPL` — the bot should return an analysis.

If the bot doesn't respond:

```bash
# Check service
sudo systemctl status stockbot-telegram

# Check logs
journalctl -u stockbot-telegram -n 30 --no-pager

# Verify env
sudo -u stockbot grep -v 'TOKEN\|KEY' /home/stockbot/stock-ai-assistant/.env
```

---

## Resource Limits (Hetzner Shared Server)

- Bind the FastAPI server to `127.0.0.1` only (`ALLOW_REMOTE_API=0`).
- The bot uses long-polling (no webhook), so no open port needed.
- Start with one worker; the bot is I/O-bound, not CPU-bound.
- Monitor memory: `systemctl status stockbot-telegram` or `htop`.
- Consider a small swap file if memory is tight (< 1 GB free).

---

## Security Notes

- The `.env` file contains the Telegram token and any API keys. Never commit it.
- Logs may contain ticker symbols but should not contain secrets.
- `TELEGRAM_ALLOWED_CHAT_IDS` restricts which Telegram users can interact with
  the bot. Keep it narrow during MVP.
- The API is bound to localhost. Do not expose it publicly unless you add
  authentication, rate limits, CORS, and security headers.
- Backups contain raw market data and snapshot payloads but no passwords.
