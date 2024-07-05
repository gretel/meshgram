# 🌐 Meshgram: Bridging Meshtastic and Telegram 🚀

Connect your Meshtastic mesh network with Telegram group chats! 📡💬

## 🌟 Features

- 🔌 Supports both serial and TCP connections to Meshtastic devices
- 🔄 Automatic reconnection to Meshtastic device
- 🚦 Message queuing and retry mechanism
- 🔔 Command to send bell notifications to Meshtastic nodes
- 📊 Real-time status updates for nodes (telemetry, position, routing, neighbors)
- 🗺️ Location sharing between Telegram and Meshtastic
- 🔐 User authorization for Telegram commands
- 📝 Optional logging to file and syslog

## 🛠 Requirements

- Python 3.12+ 🐍
- Dependencies:
  - `envyaml`: For YAML configuration file parsing with environment variable support
  - `meshtastic`: Python API for Meshtastic devices
  - `python-telegram-bot`: Telegram Bot API wrapper
  - `pubsub`: For publish-subscribe messaging pattern

## 🚀 Quick Start

1. **Clone the repo:**
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
   pip install -r requirements.txt
   ```

4. **Configure the project:**
   Create a `config.yaml` file in the `config` directory:
   ```yaml
   telegram:
     bot_token: "your_bot_token_here"
     chat_id: -1001234567890
     authorized_users:
       - 123456789

   meshtastic:
     connection_type: "serial"  # or "tcp"
     device: "/dev/ttyUSB0"  # or "hostname:port" for TCP
     default_node_id: "!abcdef12"
     local_nodes:
       - "!abcdef12"
       - "!12345678"

   logging:
     level: "info"
     level_telegram: "warn"
     level_httpx: "warn"
     use_syslog: false
     syslog_host: "localhost"
     syslog_port: 514
     syslog_protocol: "udp"
   ```

5. **Run Meshgram:**
   ```bash
   python src/meshgram.py
   ```

## 📡 Telegram Commands

- `/start` - Start the bot and see available commands
- `/help` - Show help message
- `/status` - Check the current status of Meshgram and Meshtastic
- `/bell [node_id]` - Send a bell notification to a Meshtastic node
- `/node [node_id]` - Get information about a specific node
- `/user` - Get information about your Telegram user

## 🤝 Contributing

We welcome contributions! 💖 Please open an issue or submit a pull request if you have any improvements or bug fixes.

Happy meshing! 🎉