# WelderBot

WelderBot is a Telegram bot for managing **Welder Qualification Tests (WQT)** based on **ASME Section IX**.

The project is designed with a modular architecture so that each feature can be developed, tested and maintained independently.

---

# Main Features

- Welder Management
- WQT Registration
- Contractor Management
- Project Management
- Qualification History
- Excel Certificate Export
- Authentication & Authorization
- SQLite Database

---

# Technology Stack

- Python 3
- python-telegram-bot
- SQLite
- OpenPyXL
- Pillow
- jdatetime

---

# Project Structure

```
welderbot/
├── db/
├── engine/
├── forms/
├── handlers/
├── utils/
├── data/
├── media/
├── logs/
├── config.py
├── main.py
├── requirements.txt
└── welderbot.service
```

---

# Installation

Create a virtual environment:

```bash
python -m venv .venv
```

Activate it:

Linux

```bash
source .venv/bin/activate
```

Windows

```bash
.venv\Scripts\activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

---

# Environment Variables

The project reads all sensitive values from Environment Variables.

Required variables:

```text
BOT_TOKEN
ADMIN_IDS
```

Optional:

```text
WELDERBOT_DEBUG
```

---

# Run

```bash
python main.py
```

---

# Dependencies

- python-telegram-bot
- openpyxl
- Pillow
- jdatetime

See:

```
requirements.txt
```

for exact versions.

---

# Architecture

Project architecture is documented in:

```
ARCHITECTURE.md
```

---

# Internal API

Stable APIs are documented in:

```
CONTRACTS.md
```

---

# Deployment

The project includes a ready-to-use systemd service.

```
welderbot.service
```

See:

```
RUN.md
```

for deployment instructions.

---

# License

Private Project

Copyright © Mohsen

All Rights Reserved.
