import asyncio
from typing import Dict, Any, Optional, List
from telegram import Bot, Update, BotCommand, Message, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from config_manager import ConfigManager, get_logger
import time

class RateLimiter:
    def __init__(self, max_calls: int, period: float):
        self.max_calls, self.period, self.calls = max_calls, period, []

    async def wait(self):
        now = time.time()
        self.calls = [call for call in self.calls if now - call < self.period]
        if len(self.calls) >= self.max_calls:
            await asyncio.sleep(self.period - (now - self.calls[0]))
        self.calls.append(time.time())

class TelegramInterface:
    def __init__(self, config: ConfigManager) -> None:
        self.config, self.logger = config, get_logger(__name__)
        self.bot, self.application = None, None
        self.message_queue, self._stop_event = asyncio.Queue(), asyncio.Event()
        self.chat_id, self.last_node_messages = None, {}
        self.commands = {
            'start': {'description': 'Start the bot and see available commands', 'handler': self.start_command},
            'help': {'description': 'Show help message', 'handler': self.help_command},
            'status': {'description': 'Check the current status', 'handler': self.handle_command},
            'bell': {'description': 'Send a bell to the meshtastic chat group', 'handler': self.handle_command},
            'location': {'description': 'Request location from meshtastic side', 'handler': self.handle_command},
            'telemetry': {'description': 'Request telemetry or display last received value', 'handler': self.handle_command},
            'traceroute': {'description': 'Trace route to a specific node', 'handler': self.handle_command},
            'node': {'description': 'Get information about a specific node', 'handler': self.handle_command},
            'user': {'description': 'Get information about your Telegram user', 'handler': self.user_command},
        }
        self.rate_limiter = RateLimiter(max_calls=30, period=60)

    async def setup(self) -> None:
        self.logger.info("Setting up telegram interface...")
        try:
            token = self.config.get('telegram.bot_token')
            if not token:
                raise ValueError("Telegram bot token not found in configuration")
            self.bot = Bot(token=token)
            self.application = Application.builder().token(token=token).build()
            self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.on_telegram_message))
            self.application.add_handler(MessageHandler(filters.LOCATION, self.on_telegram_location))
            for command, data in self.commands.items():
                self.application.add_handler(CommandHandler(command, data['handler']))
            await self.bot.set_my_commands([BotCommand(command, data['description']) for command, data in self.commands.items()])
            self.chat_id = self.config.get('telegram.chat_id')
            if not self.chat_id:
                raise ValueError("Telegram chat id not found in configuration")
            self.logger.info("Telegram interface set up successfully")
        except Exception as e:
            self.logger.exception(f"Failed to set up telegram: {e}")
            raise

    async def start_polling(self) -> None:
        if not self.application:
            self.logger.error("Telegram application not initialized")
            return

        self.logger.info("Starting telegram polling...")
        await self.application.initialize()
        await self.application.start()

        retry_delay = 1
        while not self._stop_event.is_set():
            try:
                await self.application.updater.start_polling(drop_pending_updates=True)
                self.logger.info("Telegram polling started")
                await self._stop_event.wait()
            except NetworkError as e:
                self.logger.error(f"Network error occurred: {e}. Retrying in {retry_delay} seconds...")
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 60)  # Exponential backoff, max 60 seconds
            except Exception as e:
                self.logger.error(f"Unexpected error in Telegram polling: {e}")
                break

        await self._shutdown_polling()

    async def _shutdown_polling(self) -> None:
        self.logger.info("Stopping telegram polling...")
        try:
            if self.application.updater.running:
                await self.application.updater.stop()
            await self.application.stop()
            await self.application.shutdown()
        except RuntimeError as e:
            self.logger.warning(f"RuntimeError during shutdown: {e}")
        except Exception as e:
            self.logger.error(f"Error during shutdown: {e}")
        self.logger.info("Telegram polling stopped")

    async def on_telegram_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        self.logger.debug(f"Received message from Telegram: {update.message.text}")
        try:
            await self.message_queue.put({
                'text': update.message.text,
                'sender': update.effective_user.username or update.effective_user.first_name,
                'type': 'telegram',
                'message_id': update.message.message_id,
                'user_id': update.effective_user.id
            })
            self.logger.info(f"Received message from Telegram: {update.message.text}")
            await update.message.reply_text("Message received and will be sent to Meshtastic.")
            await self.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        except Exception as e:
            self.logger.error(f'Error handling Telegram message: {e}')
            await update.message.reply_text("An error occurred while processing your message. Please try again.")

    async def send_message(self, text: str, disable_notification: bool = False, pin_message: bool = False) -> Optional[Message]:
        self.logger.debug(f"Attempting to send message to Telegram: {text}")
        try:
            message = await self.bot.send_message(chat_id=self.chat_id, text=text, disable_notification=disable_notification, disable_web_page_preview=True)
            self.logger.info(f"Sent message to Telegram: {text}")
            if pin_message:
                await self.bot.pin_chat_message(chat_id=self.chat_id, message_id=message.message_id)
                self.logger.info("Pinned message to Telegram")
            return message
        except Exception as e:
            self.logger.error(f"Failed to send Telegram message: {e}")
            return None

    async def send_or_update_message(self, text: str, message_id: Optional[int] = None, disable_notification: bool = False) -> None:
        await self.rate_limiter.wait()
        try:
            if message_id:
                await self.bot.edit_message_text(chat_id=self.chat_id, message_id=message_id, text=text)
            else:
                message = await self.bot.send_message(chat_id=self.chat_id, text=text, disable_notification=disable_notification)
                return message.message_id
        except Exception as e:
            self.logger.error(f"Failed to send or update telegram message: {e}")

    async def on_telegram_location(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        try:
            await self.message_queue.put({
                'location': {
                    'latitude': update.message.location.latitude,
                    'longitude': update.message.location.longitude
                },
                'sender': update.effective_user.username or update.effective_user.first_name,
                'type': 'telegram',
                'message_id': update.message.message_id
            })
            await update.message.reply_text("Location received and will be sent to meshtastic.")
        except Exception as e:
            self.logger.error(f'Error handling telegram location: {e}')
            await update.message.reply_text("An error occurred while processing your location. Please try again.")

    async def send_or_update_node_info(self, node_id: str, info_text: str) -> None:
        try:
            if node_id in self.last_node_messages:
                await self.send_or_update_message(info_text, message_id=self.last_node_messages[node_id])
            else:
                message_id = await self.send_or_update_message(info_text, disable_notification=True)
                self.last_node_messages[node_id] = message_id
            self.logger.info(f"Updated node info for {node_id}")
        except Exception as e:
            self.logger.error(f"Failed to update node info for {node_id}: {e}")

    def generate_help_text(self) -> str:
        help_text = "🚀 Welcome to Meshgram! Here are the available commands:\n\n"
        for command, data in self.commands.items():
            help_text += f"/{command} - {data['description']}\n"
        
        help_text += "\n🔍 Advanced Usage:\n"
        help_text += "Some commands can target specific nodes by adding a node ID:\n"
        help_text += "• /location [node_id] - 📍 Request location (e.g., /location !abc123)\n"
        help_text += "• /telemetry [node_id] - 📊 Request telemetry data\n"
        help_text += "• /node [node_id] - ℹ️ Get node information\n"
        help_text += "\nIf no node ID is provided, the default node will be used."
        
        return help_text

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        try:
            await update.message.reply_text(self.generate_help_text())
        except Exception as e:
            self.logger.error(f"Error in start command: {e}")
            await update.message.reply_text("An error occurred. Please try again.")

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self.start_command(update, context)

    def is_user_authorized(self, user_id: int) -> bool:
        authorized_users = self.config.get_authorized_users()
        return not authorized_users or user_id in authorized_users

    async def user_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        user_info = (f"👤 User Information:\n"
                     f"🆔 ID: {user.id}\n"
                     f"📛 Name: {user.full_name}\n"
                     f"🏷️ Username: @{user.username}\n"
                     f"🤖 Is Bot: {'Yes' if user.is_bot else 'No'}")
        await update.message.reply_text(user_info)

    async def handle_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        command = update.message.text.split()[0][1:].partition('@')[0]
        user_id = update.effective_user.id
        
        if command not in ['start', 'help', 'user', 'status'] and not self.is_user_authorized(user_id):
            await update.message.reply_text("You are not authorized to use this command.")
            return

        try:
            args = {'node_id': context.args[0]} if context.args else {}
            await self.message_queue.put({
                'type': 'command',
                'command': command,
                'args': args,
                'user_id': user_id
            })
            
            if command in ['location', 'telemetry']:
                node_id = args.get('node_id', 'default node')
                await update.message.reply_text(f"Sending {command} request to {node_id}...", disable_notification=True)
        except Exception as e:
            self.logger.error(f"Error in {command} command: {e}")
            await update.message.reply_text(f"An error occurred while processing the {command} command. Please try again.")

    async def close(self) -> None:
        self.logger.info("Stopping telegram interface...")
        self._stop_event.set()
        if self.application and self.application.updater.running:
            await self.application.updater.stop()
        if self.application:
            await self.application.stop()
            await self.application.shutdown()
        self.logger.info("Telegram interface stopped.")