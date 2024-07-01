---
# `meshgram`

**Work in progress!**

Meshgram bridges Meshtastic nodes and Telegram group chats, enabling the exchange of messages and locations between these platforms.

## Features
- Supports serial and TCP connections
- Automatic reconnection
- Rate limiting
- Regular updates
- Read receipts
- Optional syslog logging

## Requirements
- Python 3.11+
- Dependencies
	- `aiogram`
	- `envyaml`
	- `meshtastic`

## Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/gretel/meshgram.git
   cd meshgram
   ```

2. **Set up a virtual environment:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -U -r requirements.txt
   ```

4. **Configure the project:**
   - Edit `config.yaml` with your settings:
     ```yaml
     meshtastic:
       connection_type: serial  # or 'tcp'
       default_node_id: !ffffff # replace with your default node id to bridge to
     telegram:
       token: <telegram bot token>
       chat_id: <telegram chat ID>
     ```

## Usage

To start the bridge, run:
```bash
python src/meshtastic_telegram_bridge.py
```

## Contributing

Contributions are welcome! Please open an issue or submit a pull request.
