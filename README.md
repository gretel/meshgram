# 🌐 Meshgram: Bridging Meshtastic and Telegram 🚀

Connect your Meshtastic mesh network with Telegram group chats! 📡💬

## 🌟 Features

- 🔌 Supports serial and TCP connections
- 🔄 Automatic reconnection
- 🚦 Rate limiting
- 🔔 Regular updates
- ✅ Read receipts
- 📝 Optional syslog logging

## 🛠 Requirements

- Python 3.11+ 🐍
- Dependencies:
  - `envyaml` 📄
  - `meshtastic` 📡
  - `python-telegram-bot` 🤖

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
   pip install -U -r requirements.txt
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
     connection_type: "serial"
     device: "/dev/ttyUSB0"
     default_node_id: "!abcdef12"

   logging:
     level: "info"
   ```

5. **Run Meshgram:**
   ```bash
   python src/meshgram.py
   ```

## 🤝 Contributing

We love contributions! 💖 Please open an issue or submit a pull request.

## 📜 License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

Happy meshing! 🎉