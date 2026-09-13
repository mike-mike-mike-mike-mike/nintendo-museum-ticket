# Nintendo Museum Ticket Monitor

Automated monitor for available tickets at the Nintendo Museum in Kyoto, Japan.

## 🎮 What is This?

This tool checks for available tickets at the [Nintendo Museum in Kyoto](https://museum.nintendo.com/) and emails you when new dates become available. It runs as a single check per invocation — GitHub Actions triggers it on a schedule — rather than as a long-running loop.

## ✨ Features

- 🔍 Monitors Nintendo Museum ticket availability
- 🌐 Browser impersonation using `curl_cffi` (Chrome 110)
- 📧 Email notifications via Gmail SMTP
- 🎯 Smart filters:
  - Only open days (excludes Tuesdays when museum is closed)
  - Only available tickets (`sale_status == 1`)
  - Only future dates
  - No duplicate notifications — only newly-available dates trigger an email

## 📋 Prerequisites

Before you start, you'll need:

- **Python 3.13+** - [Download here](https://www.python.org/downloads/)
- **uv** - A fast Python package manager - [Install guide](https://docs.astral.sh/uv/getting-started/installation/)

### Installing uv (Easy!)

**macOS/Linux:**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows:**
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

## 🚀 Quick Start

### 1. Clone the Repository

```bash
git clone https://github.com/YOUR_USERNAME/nintendo-museum.git
cd nintendo-museum
```

### 2. Install Dependencies

Using `uv` makes this super simple:

```bash
uv sync
```

That's it! `uv` will automatically:
- Create a virtual environment
- Install all required packages
- Set everything up for you

### 3. Configure Gmail Credentials

Create a `.env` file from the example:

```bash
cp .env.example .env
```

Then edit `.env` with your settings:

```env
# Gmail credentials for notifications (app password, NOT your account password)
GMAIL_USER=you@gmail.com
GMAIL_APP_PASSWORD=your_16_char_app_password

# Where to send availability notifications
NOTIFY_EMAIL_TO=you@example.com
```

`GMAIL_APP_PASSWORD` must be a Gmail **App Password**, not your regular account
password — generate one from your Google Account's security settings.

### 4. Configure the Months to Watch

Create (or edit) `state.json` and set `config.target_months` to the months you
want checked (each as a `"YYYY-MM"` string):

```json
{
  "config": {
    "target_months": ["2026-12"]
  },
  "state": {
    "available": []
  }
}
```

Leave `state.available` as `[]` — the monitor manages that list itself and uses
it to detect newly-available dates between runs.

### 5. Run a Check

```bash
uv run main.py
```

This performs one check against every configured month, emails you about any
newly-available dates, and updates `state.json`.

## ⚙️ Configuration

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `GMAIL_USER` | Gmail address to send notifications from | Yes |
| `GMAIL_APP_PASSWORD` | Gmail App Password for that account | Yes |
| `NOTIFY_EMAIL_TO` | Address to send availability notifications to | Yes |

### `state.json`

| Field | Description |
|-------|-------------|
| `config.target_months` | List of `"YYYY-MM"` strings to check. A month that has fully elapsed is skipped. |
| `state.available` | Dates currently known to be available. Written by the monitor after each run — don't hand-edit it. |

### Scheduling

There is no interval setting to configure. In production this runs as a
GitHub Actions workflow on a `*/5 * * * *` cron schedule, checking every 5
minutes. GitHub's cron schedules are best-effort, not exact — during periods
of high load, scheduled runs routinely fire 10–30 minutes late.

## 📁 Project Structure

```
nintendo-museum/
├── main.py                # Single-shot entry point - start here!
├── state.json             # Target months + last-known availability
├── src/
│   ├── monitor.py         # Fetches and classifies calendar availability
│   ├── months.py          # "YYYY-MM" parsing helpers
│   ├── state.py           # Reads/writes state.json
│   └── notifier.py        # Gmail SMTP email notifications
├── utils/
│   └── logging_setter.py  # Logging configuration
├── logs/                  # Log files (auto-created)
├── .env                   # Your configuration (not in git)
├── .env.example           # Example configuration
├── pyproject.toml         # Python dependencies
└── README.md              # This file!
```

## 🔧 Technical Details

### API Endpoint

The monitor uses the official Nintendo Museum API:

```
GET https://museum-tickets.nintendo.com/en/api/calendar
Parameters:
  - target_year: Year (e.g., 2025)
  - target_month: Month (e.g., 11)
```

### Response Format

```json
{
  "data": {
    "calendar": {
      "2025-11-01": {
        "apply_type": 3,
        "sale_status": 2,
        "open_status": 1,
        "holiday": null,
        "day_label": null,
        "is_temporary_closure": false,
        "temporary_closure_time": null,
        "is_holding": false
      }
    }
  }
}
```

**Status Codes:**
- `sale_status = 1` → Tickets available ✅
- `sale_status = 2` → Tickets sold out ❌
- `open_status = 1` → Museum open ✅
- `open_status = 2` → Museum closed (Tuesdays) ❌

### Dependencies

- `curl-cffi` - Browser impersonation for requests
- `python-dotenv` - Environment variable management
- Email is sent using Python's standard library (`smtplib`, `email`) — no extra dependency

## 📝 Logs

Logs are automatically saved in the `logs/` directory:
- `nintendo_main.log` - Orchestration logs (`main.py`)
- `nintendo_monitor.log` - Fetch/classification logs (`src/monitor.py`)
- `nintendo_notifier.log` - Email send logs (`src/notifier.py`)

## 🔥 Troubleshooting

### "environment variable ... is not set"

One of `GMAIL_USER`, `GMAIL_APP_PASSWORD`, or `NOTIFY_EMAIL_TO` is missing.
Check your `.env` file:
```bash
cat .env
```

### "config.target_months must be a non-empty list"

`state.json` is missing `config.target_months`, or it isn't a non-empty list.
Fix the file as shown in [Configure the Months to Watch](#4-configure-the-months-to-watch).

### "Every configured target month has fully elapsed"

Every month in `config.target_months` is entirely in the past. Update
`state.json` with a current or future month.

### "Module not found" errors

Reinstall dependencies:
```bash
uv sync
```

## ℹ️ Important Notes

**Museum Closure:**
The Nintendo Museum is **closed on Tuesdays**. The monitor automatically skips these days.

**Responsible Use:**
This tool is for personal use only. Please respect Nintendo's terms of service and don't abuse the API.

## 🔗 Useful Links

- [Nintendo Museum Official Website](https://museum.nintendo.com/)
- [Nintendo Museum Ticket Booking](https://museum-tickets.nintendo.com/en/calendar)
- [uv Documentation](https://docs.astral.sh/uv/)

## 📄 License

MIT License - See [LICENSE](LICENSE) file for details.

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## ⚠️ Disclaimer

This tool is for informational purposes only. Please respect the Nintendo Museum website's terms of service. The authors are not responsible for any misuse of this tool.

---

**Made with ❤️ for Nintendo fans worldwide**

*Having trouble? [Open an issue](https://github.com/YOUR_USERNAME/nintendo-museum/issues)*
