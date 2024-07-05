from __future__ import annotations

import asyncio
from typing import TypedDict, Literal, Protocol, Any, NotRequired
from collections.abc import Awaitable
from datetime import datetime, timezone, timedelta
from telegram import Update
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown
from meshtastic_interface import MeshtasticInterface
from telegram_interface import TelegramInterface
from config_manager import ConfigManager, get_logger
from node_manager import NodeManager

class CommandHandler(Protocol):
    async def __call__(self, args: list[str], user_id: int, update: Update) -> None:
        ...

class MeshtasticPacket(TypedDict):
    fromId: str
    toId: str
    decoded: dict[str, Any]
    id: str

class TelegramMessage(TypedDict):
    type: Literal['command', 'telegram', 'location', 'reaction']
    text: NotRequired[str]
    sender: NotRequired[str]
    message_id: NotRequired[int]
    user_id: NotRequired[int]
    command: NotRequired[str]
    args: NotRequired[list[str]]
    update: NotRequired[Update]
    location: NotRequired[dict[str, float]]
    emoji: NotRequired[str]
    original_message_id: NotRequired[int]

class PendingAck(TypedDict):
    telegram_message_id: int
    timestamp: datetime

class MessageProcessor:
    def __init__(self, meshtastic: MeshtasticInterface, telegram: TelegramInterface, config: ConfigManager) -> None:
        self.config: ConfigManager = config
        self.logger = get_logger(__name__)
        self.meshtastic: MeshtasticInterface = meshtastic
        self.telegram: TelegramInterface = telegram
        self.node_manager: NodeManager = meshtastic.node_manager
        self.start_time: datetime = datetime.now(timezone.utc)
        self.local_nodes: list[str] = config.get('meshtastic.local_nodes', [])
        self.is_closing: bool = False
        self.processing_tasks: list[asyncio.Task] = []
        self.message_id_map: dict[int, str] = {}
        self.reverse_message_id_map: dict[str, int] = {}
        self.pending_acks: dict[int, PendingAck] = {}
        self.ack_timeout: int = 60  # seconds

    async def process_messages(self) -> None:
        self.processing_tasks = [
            asyncio.create_task(self.process_meshtastic_messages()),
            asyncio.create_task(self.process_telegram_messages()),
            asyncio.create_task(self.process_pending_acks())
        ]
        try:
            await asyncio.gather(*self.processing_tasks)
        except asyncio.CancelledError:
            self.logger.info("Message processing tasks cancelled.")
        finally:
            await self.close()

    async def process_meshtastic_messages(self) -> None:
        while not self.is_closing:
            try:
                message: MeshtasticPacket = await self.meshtastic.message_queue.get()
                self.logger.debug(f"Processing Meshtastic message: {message=}")
                match message.get('type'):
                    case 'ack':
                        await self.handle_ack(message)
                    case _:
                        await self.handle_meshtastic_message(message)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error processing Meshtastic message: {e=}", exc_info=True)
            await asyncio.sleep(0.1)

    async def process_telegram_messages(self) -> None:
        while not self.is_closing:
            try:
                message: TelegramMessage = await self.telegram.message_queue.get()
                self.logger.info(f"Processing Telegram message: {message=}")
                await self.handle_telegram_message(message)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error processing Telegram message: {e=}", exc_info=True)
            await asyncio.sleep(0.1)

    async def handle_meshtastic_message(self, packet: Dict[str, Any]) -> None:
        self.logger.debug(f"Received Meshtastic message: {packet=}")
        
        if packet.get('type') == 'ack':
            await self.handle_ack(packet)
        else:
            portnum = packet.get('decoded', {}).get('portnum', '')
            handler = getattr(self, f"handle_{portnum.lower()}", None)
            if handler:
                self.logger.info(f"Handling Meshtastic message type {portnum=} from {packet.get('fromId')=}")
                await handler(packet)
            else:
                self.logger.warning(f"Unhandled Meshtastic message type: {portnum=} from: {packet.get('fromId')=}")

    async def handle_ack(self, packet: Dict[str, Any]) -> None:
        message_id = packet.get('id')
        if message_id is None:
            self.logger.warning("Received ACK without message ID")
            return

        pending_message = self.pending_acks.pop(message_id, None)
        if pending_message:
            telegram_message_id = pending_message.get('telegram_message_id')
            if telegram_message_id:
                await self.telegram.add_reaction(telegram_message_id, '✅')
                self.logger.info(f"ACK processed for message ID: {message_id}, Telegram message ID: {telegram_message_id}")
            else:
                self.logger.warning(f"ACK received for message ID {message_id}, but no Telegram message ID found")
        else:
            self.logger.warning(f"Received ACK for unknown message ID: {message_id}")

    async def handle_text_message_app(self, packet: Dict[str, Any]) -> None:
        text: str = packet['decoded']['payload'].decode('utf-8')
        sender, recipient = packet.get('fromId', 'unknown'), packet.get('toId', 'unknown')
        
        message: str = f"📡 Meshtastic: {sender} → {recipient}\n💬 {text}"
        self.logger.info(f"Sending Meshtastic message to Telegram: {message=}")
        await self.telegram.send_message(message, disable_notification=False)

    async def handle_telegram_text(self, message: Dict[str, Any]) -> None:
        self.logger.info(f"Handling Telegram text message: {message}")
        sender = message['sender'][:10]
        recipient = self.config.get('meshtastic.default_node_id')
        text = message['text']
        telegram_message_id = message['message_id']
        
        meshtastic_message = f"[TG:{sender}] {text}"
        self.logger.info(f"Preparing to send Telegram message to Meshtastic: {meshtastic_message}")
        try:
            meshtastic_message_id = await self.meshtastic.send_message(meshtastic_message, recipient)
            self.logger.info(f"Successfully sent message to Meshtastic: {meshtastic_message}")
            
            self.pending_acks[meshtastic_message_id] = {
                'telegram_message_id': telegram_message_id,
                'timestamp': datetime.now(timezone.utc)
            }
            
            asyncio.create_task(self.remove_pending_ack(meshtastic_message_id))
        except Exception as e:
            self.logger.error(f"Failed to send message to Meshtastic: {e}", exc_info=True)
            await self.telegram.send_message("Failed to send message to Meshtastic. Please try again.")

    async def remove_pending_ack(self, message_id: str) -> None:
        await asyncio.sleep(self.ack_timeout)
        if message_id in self.pending_acks:
            self.logger.warning(f"ACK timeout for message ID: {message_id}")
            del self.pending_acks[message_id]

    async def process_pending_acks(self) -> None:
        while True:
            now = datetime.now(timezone.utc)
            for message_id, data in list(self.pending_acks.items()):
                if (now - data['timestamp']).total_seconds() > self.ack_timeout:
                    self.logger.warning(f"ACK timeout for message ID: {message_id}")
                    del self.pending_acks[message_id]
            await asyncio.sleep(10)  # Check every 10 seconds

    async def handle_telegram_message(self, message: TelegramMessage) -> None:
        handlers: dict[str, CommandHandler] = {
            'command': self.handle_telegram_command,
            'telegram': self.handle_telegram_text,
            'location': self.handle_telegram_location,
            'reaction': self.handle_telegram_reaction
        }
        handler = handlers.get(message['type'])
        if handler:
            await handler(message)
        else:
            self.logger.warning(f"Received unknown message type: {message['type']=}")

    def _store_message_id_mapping(self, telegram_id: int, meshtastic_id: str) -> None:
        self.message_id_map[telegram_id] = meshtastic_id
        self.reverse_message_id_map[meshtastic_id] = telegram_id

    def _get_meshtastic_message_id(self, telegram_message_id: int) -> str | None:
        return self.message_id_map.get(telegram_message_id)

    def _get_telegram_message_id(self, meshtastic_message_id: str) -> int | None:
        return self.reverse_message_id_map.get(meshtastic_message_id)

    async def update_message_status(self, meshtastic_message_id: str, status: str) -> None:
        telegram_message_id = self._get_telegram_message_id(meshtastic_message_id)
        if telegram_message_id:
            await self.telegram.update_message_status(telegram_message_id, status)
        else:
            self.logger.warning(f"Could not find corresponding Telegram message for Meshtastic message ID: {meshtastic_message_id}")

    async def handle_telegram_location(self, message: TelegramMessage) -> None:
        location = message.get('location', {})
        lat, lon = location.get('latitude'), location.get('longitude')
        alt = location.get('altitude', 0)
        sender = message.get('sender', 'unknown')
        try:
            if not self.is_valid_coordinate(lat, lon, alt):
                raise ValueError("Invalid coordinates")

            recipient = self.config.get('meshtastic.default_node_id')
            await self.meshtastic.send_message(f"[TG:{sender}] location lat={lat:.6f}, lon={lon:.6f}, alt={alt:.1f}m", recipient)
            await self.telegram.send_message(f"📍 Location sent to Meshtastic network: lat={lat:.6f}, lon={lon:.6f}, alt={alt:.1f}m")
        except ValueError as e:
            self.logger.error(f"Invalid location data: {e}")
            await self.telegram.send_message(f"Failed to send location to Meshtastic. Invalid data: {e}")
        except Exception as e:
            self.logger.error(f"Failed to send location to Meshtastic: {e}", exc_info=True)
            await self.telegram.send_message("Failed to send location to Meshtastic. Please try again.")

    def is_valid_coordinate(self, lat: float | None, lon: float | None, alt: float) -> bool:
        return (lat is not None and lon is not None and
                -90 <= lat <= 90 and -180 <= lon <= 180 and -1000 <= alt <= 50000)

    async def handle_telegram_command(self, message: TelegramMessage) -> None:
        try:
            command = message.get('command', '').partition('@')[0]
            args = message.get('args', [])
            user_id = message.get('user_id')
            update = message.get('update')

            if not user_id or not update:
                self.logger.error("Missing user_id or update in command message")
                return

            if not self.telegram.is_user_authorized(user_id) and command not in ['start', 'help', 'user']:
                await update.message.reply_text("You are not authorized to use this command.")
                return

            handler = getattr(self, f"cmd_{command}", None)
            if handler:
                await handler(args, user_id, update)
            else:
                await update.message.reply_text(f"Unknown command: {command}")
        except Exception as e:
            self.logger.error(f'Error handling Telegram command: {e}', exc_info=True)
            if update and update.message:
                await update.message.reply_text(f"Error executing command: {e}")

    async def handle_telegram_reaction(self, message: TelegramMessage) -> None:
        self.logger.info(f"Processing reaction: {message}")
        emoji = message.get('emoji')
        original_message_id = message.get('original_message_id')
        
        if not emoji or not original_message_id:
            self.logger.error("Missing emoji or original_message_id in reaction message")
            return

        meshtastic_message_id = self._get_meshtastic_message_id(original_message_id)
        
        if meshtastic_message_id:
            await self.meshtastic.send_reaction(emoji, meshtastic_message_id)
        else:
            self.logger.warning(f"Could not find corresponding Meshtastic message for Telegram message ID: {original_message_id}")

    async def cmd_start(self, args: list[str], user_id: int, update: Update) -> None:
        welcome_message = (
            "Welcome to Meshgram! 🌐📱\n\n"
            "This bot bridges your Telegram chat with a Meshtastic mesh network.\n"
            "Use /help to see available commands."
        )
        await update.message.reply_text(escape_markdown(welcome_message, version=2), parse_mode=ParseMode.MARKDOWN_V2)

    async def cmd_help(self, args: list[str], user_id: int, update: Update) -> None:
        help_text = (
            "Available commands:\n\n"
            "/start - Start the bot and see welcome message\n"
            "/help - Show this help message\n"
            "/status - Check the current status of Meshgram and Meshtastic\n"
            "/bell [node_id] - Send a bell notification to a Meshtastic node\n"
            "/node [node_id] - Get information about a specific node\n"
            "/user - Get information about your Telegram user"
        )
        await update.message.reply_text(escape_markdown(help_text, version=2), parse_mode=ParseMode.MARKDOWN_V2)

    async def cmd_status(self, args: list[str], user_id: int, update: Update) -> None:
        status: str = await self.get_status()
        await update.message.reply_text(status, parse_mode=ParseMode.MARKDOWN_V2)

    async def cmd_bell(self, args: list[str], user_id: int, update: Update) -> None:
        dest_id: str = args[0] if args else self.config.get('meshtastic.default_node_id')
        if not dest_id:
            await update.message.reply_text("No node ID provided and no default node ID set.")
            return
        self.logger.info(f"Sending bell to node {dest_id=}")
        try:
            await self.meshtastic.send_bell(dest_id)
            await update.message.reply_text(
                escape_markdown(f"🔔 Bell sent to node {dest_id}.", version=2),
                parse_mode=ParseMode.MARKDOWN_V2,
                disable_notification=True
            )
        except Exception as e:
            self.logger.error(f"Failed to send bell to node {dest_id=}: {e=}", exc_info=True)
            await update.message.reply_text(
                escape_markdown(f"Failed to send bell to node {dest_id}. Error: {str(e)}", version=2),
                parse_mode=ParseMode.MARKDOWN_V2
            )

    async def cmd_node(self, args: list[str], user_id: int, update: Update) -> None:
        node_id: str = args[0] if args else self.config.get('meshtastic.default_node_id')
        if not node_id:
            await update.message.reply_text("No node ID provided and no default node ID set.")
            return
        node_info: str = self.node_manager.format_node_info(node_id)
        telemetry_info: str = self.node_manager.get_node_telemetry(node_id)
        position_info: str = self.node_manager.get_node_position(node_id)
        routing_info: str = self.node_manager.format_node_routing(node_id)
        neighbor_info: str = self.node_manager.format_node_neighbors(node_id)
        sensor_info: str = self.node_manager.get_node_sensor_info(node_id)
        
        full_info: str = f"{node_info}\n\n{telemetry_info}\n\n{position_info}\n\n{routing_info}\n\n{neighbor_info}\n\n{sensor_info}"
        await update.message.reply_text(escape_markdown(full_info, version=2), parse_mode=ParseMode.MARKDOWN_V2)

    async def cmd_user(self, args: list[str], user_id: int, update: Update) -> None:
        user = update.effective_user
        user_info = (
            f"User Information:\n"
            f"ID: {user.id}\n"
            f"Username: @{user.username}\n"
            f"First Name: {user.first_name}\n"
            f"Last Name: {user.last_name}\n"
            f"Is Bot: {'Yes' if user.is_bot else 'No'}\n"
            f"Language Code: {user.language_code}\n"
            f"Is Authorized: {'Yes' if self.telegram.is_user_authorized(user.id) else 'No'}"
        )
        await update.message.reply_text(escape_markdown(user_info, version=2), parse_mode=ParseMode.MARKDOWN_V2)

    async def get_status(self) -> str:
        uptime: timedelta = datetime.now(timezone.utc) - self.start_time
        meshtastic_status: str = await self.meshtastic.get_status()
        num_nodes: int = len(self.node_manager.get_all_nodes())
        
        status_lines: list[str] = [
            "📊 *Meshgram Status*:",
            f"⏱️ Uptime: `{self._format_uptime(uptime.total_seconds())}`",
            f"🔢 Connected Nodes: `{num_nodes}`",
            "",
            "📡 *Meshtastic Status*:"
        ]
        
        for line in meshtastic_status.split('\n'):
            key, value = line.split(': ', 1)
            status_lines.append(f"{key}: `{escape_markdown(value, version=2)}`")
        
        return "\n".join(status_lines)

    async def close(self) -> None:
        if self.is_closing:
            self.logger.info("MessageProcessor is already closing, skipping.")
            return

        self.is_closing = True
        self.logger.info("Closing MessageProcessor...")
        
        for task in self.processing_tasks:
            if not task.done():
                task.cancel()
        
        if self.processing_tasks:
            await asyncio.gather(*self.processing_tasks, return_exceptions=True)
        
        self.processing_tasks.clear()
        self.is_closing = False
        self.logger.info("MessageProcessor closed.")

    def _format_uptime(self, seconds: float) -> str:
        days, remainder = divmod(int(seconds), 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, _ = divmod(remainder, 60)
        return f"{days}d {hours:02d}h {minutes:02d}m"

    def _format_channel_utilization(self, value: float) -> str:
        return f"{value:.2f}%" if isinstance(value, (int, float)) else str(value)

    async def _update_telemetry_message(self, node_id: str, telemetry_data: dict[str, Any]) -> None:
        self.node_manager.update_node_telemetry(node_id, telemetry_data)
        telemetry_info = self.node_manager.get_node_telemetry(node_id)
        await self.telegram.send_or_edit_message('telemetry', node_id, telemetry_info)

    async def _update_location_message(self, node_id: str, position_data: dict[str, Any]) -> None:
        self.node_manager.update_node_position(node_id, position_data)
        position_info = self.node_manager.get_node_position(node_id)
        await self.telegram.send_or_edit_message('location', node_id, position_info)

    def _get_battery_status(self, battery_level: int) -> str:
        return "PWR" if battery_level == 101 else f"{battery_level}%"

    async def handle_nodeinfo_app(self, packet: MeshtasticPacket) -> None:
        node_id: str = packet.get('fromId', 'unknown')
        node_info: dict[str, Any] = packet['decoded']
        self.node_manager.update_node(node_id, {
            'shortName': node_info.get('user', {}).get('shortName', 'unknown'),
            'longName': node_info.get('user', {}).get('longName', 'unknown'),
            'hwModel': node_info.get('user', {}).get('hwModel', 'unknown')
        })
        info_text: str = self.node_manager.format_node_info(node_id)
        await self.telegram.send_or_edit_message('nodeinfo', node_id, info_text)

    async def handle_position_app(self, packet: MeshtasticPacket) -> None:
        position = packet['decoded'].get('position', {})
        node_id = packet.get('fromId', 'unknown')
        self.node_manager.update_node_position(node_id, position)
        position_info = self.node_manager.get_node_position(node_id)
        await self.telegram.send_or_edit_message('location', node_id, position_info)
        
        latitude = position.get('latitudeI', 0) / 1e7
        longitude = position.get('longitudeI', 0) / 1e7
        if latitude != 0 and longitude != 0:
            await self.telegram.bot.send_location(chat_id=self.telegram.chat_id, latitude=latitude, longitude=longitude)

    async def handle_telemetry_app(self, packet: MeshtasticPacket) -> None:
        node_id = packet.get('fromId', 'unknown')
        telemetry = packet.get('decoded', {}).get('telemetry', {})
        device_metrics = telemetry.get('deviceMetrics', {})
        self.node_manager.update_node_telemetry(node_id, device_metrics)
        telemetry_info = self.node_manager.get_node_telemetry(node_id)
        await self.telegram.send_or_edit_message('telemetry', node_id, telemetry_info)

    async def handle_admin_app(self, packet: dict[str, Any]) -> None:
        admin_message = packet.get('decoded', {}).get('admin', {})
        if 'getRouteReply' in admin_message:
            await self._handle_route_reply(admin_message, packet.get('toId', 'unknown'))
        elif 'deviceMetrics' in admin_message:
            await self._handle_device_metrics(packet.get('fromId', 'unknown'), admin_message['deviceMetrics'])
        elif 'position' in admin_message:
            await self._handle_position(packet.get('fromId', 'unknown'), admin_message['position'])
        else:
            self.logger.warning(f"Received unexpected admin message: {admin_message}")

    async def _handle_route_reply(self, admin_message: dict[str, Any], dest_id: str) -> None:
        route = admin_message['getRouteReply'].get('route', [])
        if route:
            route_str = " → ".join(f"!{node:08x}" for node in route)
            traceroute_result = f"🔍 Traceroute to {dest_id}:\n{route_str}"
        else:
            traceroute_result = f"🔍 Traceroute to {dest_id}: No route found"
        await self.telegram.send_message(escape_markdown(traceroute_result, version=2), parse_mode=ParseMode.MARKDOWN_V2)

    async def _handle_device_metrics(self, node_id: str, device_metrics: dict[str, Any]) -> None:
        self.node_manager.update_node_telemetry(node_id, device_metrics)
        telemetry_info = self.node_manager.get_node_telemetry(node_id)
        await self.telegram.send_or_edit_message('telemetry', node_id, telemetry_info)

    async def _handle_position(self, node_id: str, position: dict[str, Any]) -> None:
        self.node_manager.update_node_position(node_id, position)
        position_info = self.node_manager.get_node_position(node_id)
        await self.telegram.send_or_edit_message('location', node_id, position_info)

    def start_background_tasks(self) -> None:
        self.processing_tasks.append(asyncio.create_task(self.process_pending_acks()))