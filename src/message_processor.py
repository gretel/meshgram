import asyncio
from typing import Dict, Any
from datetime import datetime, timezone
from meshtastic_interface import MeshtasticInterface
from telegram_interface import TelegramInterface
from config_manager import ConfigManager, get_logger

class MessageProcessor:
    def __init__(self, meshtastic: MeshtasticInterface, telegram: TelegramInterface, config: ConfigManager) -> None:
        self.config = config
        self.logger = get_logger(__name__)
        self.meshtastic = meshtastic
        self.telegram = telegram
        self.node_manager = meshtastic.node_manager
        self.start_time = datetime.now(timezone.utc)
        self.last_heartbeat = {}
        self.heartbeat_timeout = config.get('meshtastic.heartbeat_timeout', 300)
        self.local_nodes = config.get('meshtastic.local_nodes', [])
        self.pending_requests = {}  # For tracking location, telemetry, and traceroute requests

    async def handle_meshtastic_message(self, packet: Dict[str, Any]) -> None:
        self.logger.debug(f"Received Meshtastic message: {packet}")
        if packet.get('fromId') not in self.local_nodes:
            self.logger.info(f"Message from non-local node: {packet.get('fromId')}")
        
        try:
            portnum = packet.get('decoded', {}).get('portnum')
            handler = getattr(self, f"handle_{portnum.lower()}", None)
            if handler:
                self.logger.info(f"Handling Meshtastic message type: {portnum}")
                await handler(packet)
            else:
                self.logger.warning(f"Unhandled Meshtastic message type: {portnum}")
        except Exception as e:
            self.logger.error(f'Error handling Meshtastic message: {e}', exc_info=True)

    async def handle_text_message_app(self, packet: Dict[str, Any]) -> None:
        text = packet['decoded']['payload'].decode('utf-8')
        sender, recipient = packet.get('fromId', 'unknown'), packet.get('toId', 'unknown')
        
        message = f"[Meshtastic:{sender}->{recipient}] {text}"
        self.logger.info(f"Sending Meshtastic message to Telegram: {message}")
        await self.telegram.send_message(message, disable_notification=False)

    async def handle_telegram_text(self, message: Dict[str, Any]) -> None:
        self.logger.info(f"Handling Telegram text message: {message}")
        sender = message['sender'][:10]
        recipient = self.config.get('meshtastic.default_node_id', '^all')
        text = message['text']
        
        meshtastic_message = f"[TG:{sender}] {text}"
        self.logger.info(f"Preparing to send Telegram message to Meshtastic: {meshtastic_message}")
        try:
            await self.meshtastic.send_message(meshtastic_message, recipient)
            self.logger.info(f"Successfully sent message to Meshtastic: {meshtastic_message}")
        except Exception as e:
            self.logger.error(f"Failed to send message to Meshtastic: {e}", exc_info=True)
            await self.telegram.send_message("Failed to send message to Meshtastic. Please try again.")

        # Add this line to check if the message is being processed
        self.logger.info("Finished handling Telegram text message")

    async def handle_position_app(self, packet: Dict[str, Any]) -> None:
        position = packet['decoded'].get('position', {})
        sender = packet.get('fromId', 'unknown')
        self.node_manager.update_node_position(sender, position)
        position_info = self.node_manager.get_node_position(sender)
        await self.update_or_send_message('location', sender, position_info)

    async def handle_telemetry_app(self, packet: Dict[str, Any]) -> None:
        node_id = packet.get('fromId', 'unknown')
        telemetry = packet.get('decoded', {}).get('telemetry', {})
        device_metrics = telemetry.get('deviceMetrics', {})
        self.node_manager.update_node_telemetry(node_id, device_metrics)
        self.last_heartbeat[node_id] = datetime.now(timezone.utc)
        telemetry_info = self.node_manager.get_node_telemetry(node_id)
        await self.update_or_send_message('telemetry', node_id, telemetry_info)

    async def handle_admin_app(self, packet: Dict[str, Any]) -> None:
        admin_message = packet.get('decoded', {}).get('admin', {})
        self.logger.info(f"Received admin message: {admin_message}")
        if 'getRouteReply' in admin_message:
            route = admin_message['getRouteReply'].get('route', [])
            dest_id = packet.get('toId', 'unknown')
            route_str = " -> ".join(map(str, route)) if route else "No route found"
            traceroute_result = f"🔍 Traceroute to {dest_id}:\n{route_str}"
            await self.update_or_send_message('traceroute', dest_id, traceroute_result)
        elif 'getChannelResponse' in admin_message:
            self.logger.info(f"Received channel response: {admin_message['getChannelResponse']}")
        else:
            self.logger.warning(f"Unhandled admin message: {admin_message}")

    async def update_or_send_message(self, request_type: str, node_id: str, content: str) -> None:
        request_key = f"{request_type}:{node_id}"
        if request_key in self.pending_requests:
            await self.telegram.send_or_update_message(content, message_id=self.pending_requests[request_key])
            del self.pending_requests[request_key]
        else:
            await self.telegram.send_message(content, disable_notification=True)

    async def process_messages(self) -> None:
        tasks = [
            self.process_meshtastic_messages(),
            self.process_telegram_messages(),
            self.periodic_status_update(),
            self.check_heartbeats()
        ]
        await asyncio.gather(*tasks)

    async def process_meshtastic_messages(self) -> None:
        while True:
            try:
                message = await self.meshtastic.message_queue.get()
                self.logger.debug(f"Processing Meshtastic message: {message}")
                if 'decoded' in message and 'portnum' in message['decoded']:
                    await self.handle_meshtastic_message(message)
                else:
                    self.logger.warning(f"Received unexpected message format: {message}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error processing Meshtastic message: {e}", exc_info=True)
            await asyncio.sleep(0.1)

    async def process_telegram_messages(self) -> None:
        while True:
            try:
                self.logger.debug("Waiting for Telegram message...")
                message = await self.telegram.message_queue.get()
                self.logger.info(f"Processing Telegram message: {message}")
                if message['type'] == 'command':
                    await self.handle_telegram_command(message)
                elif message['type'] == 'telegram':
                    await self.handle_telegram_text(message)
                elif message['type'] == 'location':
                    await self.handle_telegram_location(message)
                else:
                    self.logger.warning(f"Received unknown message type: {message['type']}")
                self.logger.debug("Finished processing Telegram message")
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error processing Telegram message: {e}", exc_info=True)
            await asyncio.sleep(0.1)

    async def periodic_status_update(self) -> None:
        while True:
            try:
                await asyncio.sleep(3600)
                status = await self.get_status()
                await self.telegram.send_message(status)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in periodic status update: {e}", exc_info=True)

    async def get_status(self) -> str:
        uptime = datetime.now(timezone.utc) - self.start_time
        meshtastic_status = await self.meshtastic.get_status()
        num_nodes = len(self.node_manager.get_all_nodes())
        return f"Meshgram Status:\nUptime: {uptime}\nConnected Nodes: {num_nodes}\nMeshtastic Status:\n{meshtastic_status}"

    async def handle_nodeinfo_app(self, packet: Dict[str, Any]) -> None:
        node_id = packet.get('from', 'unknown')
        node_info = packet['decoded']
        self.node_manager.update_node(node_id, {
            'shortName': node_info.get('user', {}).get('shortName', 'unknown'),
            'longName': node_info.get('user', {}).get('longName', 'unknown'),
            'hwModel': node_info.get('user', {}).get('hwModel', 'unknown')
        })
        await self.telegram.send_message(self.node_manager.format_node_info(node_id), disable_notification=True)

    async def handle_telegram_command(self, message: Dict[str, Any]) -> None:
        try:
            command = message.get('command', '').partition('@')[0]
            args, user_id = message.get('args', {}), message.get('user_id')

            if not self.telegram.is_user_authorized(user_id) and command not in ['start', 'help', 'user']:
                await self.telegram.send_message("You are not authorized to use this command.")
                return

            handler = getattr(self, f"cmd_{command}", None)
            if handler:
                await handler(args, user_id)
            else:
                await self.telegram.send_message(f"Unknown command: {command}")
        except Exception as e:
            self.logger.error(f'Error handling Telegram command: {e}', exc_info=True)
            await self.telegram.send_message(f"Error executing command: {e}")

    def validate_node_id(self, node_id: str) -> bool:
        return len(node_id) == 8 and all(c in '0123456789abcdefABCDEF' for c in node_id)

    async def handle_telegram_location(self, message: Dict[str, Any]) -> None:
        lat, lon = message['location']['latitude'], message['location']['longitude']
        sender = message['sender']
        await self.meshtastic.send_location(lat, lon, f"Location from telegram user {sender}")

    async def cmd_status(self, args: Dict[str, Any], user_id: int) -> None:
        nodes = self.node_manager.get_all_nodes()
        total_nodes = len(nodes)
        active_nodes = sum(1 for node in nodes.values() if 'last_updated' in node)
        
        status_text = f"📊 Meshgram Status\n🔢 Total nodes: {total_nodes}\n✅ Active nodes: {active_nodes}\n\n"
        for node_id, node_info in nodes.items():
            status_text += (f"🔷 Node {node_id}:\n"
                            f"📛 Name: {node_info.get('name', 'Unknown')}\n"
                            f"🔋 Battery: {node_info.get('batteryLevel', 'Unknown')}\n"
                            f"⏱️ Uptime: {node_info.get('uptimeSeconds', 'Unknown')} seconds\n"
                            f"🕒 Last updated: {node_info.get('last_updated', 'Unknown')}\n\n")
        
        await self.telegram.send_message(status_text)

    async def cmd_node(self, args: Dict[str, Any], user_id: int) -> None:
        node_id = args.get('node_id') or self.config.get('meshtastic.default_node_id')
        if not node_id:
            await self.telegram.send_message("No node ID provided and no default node ID set.")
            return
        node_info = self.node_manager.format_node_info(node_id)
        await self.telegram.send_message(node_info)

    async def cmd_bell(self, args: Dict[str, Any], user_id: int) -> None:
        dest_id = args.get('node_id') or self.config.get('meshtastic.default_node_id')
        self.logger.info(f"Sending bell to node {dest_id}")
        try:
            await self.meshtastic.send_bell(dest_id)
            self.logger.info(f"Bell sent successfully to node {dest_id}")
            await self.telegram.send_message(f"🔔 Bell sent to node {dest_id}.", disable_notification=True)
        except Exception as e:
            self.logger.error(f"Failed to send bell to node {dest_id}: {e}", exc_info=True)
            await self.telegram.send_message(f"Failed to send bell to node {dest_id}. Error: {str(e)}")

    async def cmd_location(self, args: Dict[str, Any], user_id: int) -> None:
        dest_id = args.get('node_id') or self.config.get('meshtastic.default_node_id')
        await self.meshtastic.request_location(dest_id)
        message = await self.telegram.send_message(f"📍 Location request sent to node {dest_id}. Waiting for response...")
        if message:
            self.pending_requests[f"location:{dest_id}"] = message.message_id

    async def cmd_telemetry(self, args: Dict[str, Any], user_id: int) -> None:
        dest_id = args.get('node_id') or self.config.get('meshtastic.default_node_id')
        await self.meshtastic.request_telemetry(dest_id)
        message = await self.telegram.send_message(f"📊 Telemetry request sent to node {dest_id}. Waiting for response...")
        if message:
            self.pending_requests[f"telemetry:{dest_id}"] = message.message_id

    async def cmd_traceroute(self, args: Dict[str, Any], user_id: int) -> None:
        dest_id = args.get('node_id') or self.config.get('meshtastic.default_node_id')
        message = await self.telegram.send_message(f"🔍 Initiating traceroute to {dest_id}...")
        if message:
            self.pending_requests[f"traceroute:{dest_id}"] = message.message_id
        await self.meshtastic.traceroute(dest_id)

    async def check_heartbeats(self) -> None:
        while True:
            try:
                now = datetime.now(timezone.utc)
                for node_id, last_heartbeat in list(self.last_heartbeat.items()):
                    if (now - last_heartbeat).total_seconds() > self.heartbeat_timeout:
                        del self.last_heartbeat[node_id]
                        await self.telegram.send_message(f"⚠️ Node {node_id} is no longer active.")
                await asyncio.sleep(60)
            except Exception as e:
                self.logger.error(f"Error in check_heartbeats: {e}", exc_info=True)
                await asyncio.sleep(60)

    async def close(self) -> None:
        self.logger.info("Closing MessageProcessor...")
        # Add any cleanup operations here if needed
        self.logger.info("MessageProcessor closed.")
