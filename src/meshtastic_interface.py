import asyncio
import queue
from typing import Dict, Any, Optional, Union, List
from dataclasses import dataclass
from datetime import datetime, timedelta
from meshtastic import tcp_interface, serial_interface
from meshtastic.serial_interface import SerialInterface
from meshtastic.tcp_interface import TCPInterface
from pubsub import pub
from config_manager import ConfigManager, get_logger
from node_manager import NodeManager

@dataclass
class PendingMessage:
    text: str
    recipient: str
    attempts: int = 0
    last_attempt: Optional[datetime] = None

class MeshtasticInterface:
    def __init__(self, config: ConfigManager) -> None:
        self.config = config
        self.logger = get_logger(__name__)
        self.interface: Optional[Union[SerialInterface, TCPInterface]] = None
        self.message_queue = asyncio.Queue()
        self.thread_safe_queue = queue.Queue()
        self.loop = asyncio.get_event_loop()
        self.pending_messages: List[PendingMessage] = []
        self.last_telemetry: Dict[str, Any] = {}
        self.max_retries, self.retry_interval = 3, 60
        self.node_manager = NodeManager()
        self.is_setup = False

    async def setup(self) -> None:
        self.logger.info("Setting up meshtastic interface...")
        try:
            self.interface = await self._create_interface()
            pub.subscribe(self.on_meshtastic_message, "meshtastic.receive")
            pub.subscribe(self.on_connection, "meshtastic.connection.established")
            await self._fetch_node_info()
            self.is_setup = True
            self.logger.info("Meshtastic interface setup complete.")
        except Exception as e:
            self.logger.error(f"Failed to set up Meshtastic interface: {e}", exc_info=True)
            raise

    async def _create_interface(self) -> Union[SerialInterface, TCPInterface]:
        connection_type = self.config.get('meshtastic.connection_type', 'serial')
        device = self.config.get('meshtastic.device')
        if not device:
            raise ValueError("Meshtastic device is not configured in the YAML file.")
        
        if connection_type == 'serial':
            return await asyncio.to_thread(serial_interface.SerialInterface, device)
        elif connection_type == 'tcp':
            host, port = device.split(':')
            return await asyncio.to_thread(tcp_interface.TCPInterface, hostname=host, port=int(port))
        else:
            raise ValueError(f"Unsupported connection type: {connection_type}")

    async def _fetch_node_info(self) -> None:
        try:
            node_info = await asyncio.to_thread(self.interface.getMyNodeInfo)
            await self.send_node_info(node_info)
        except Exception as e:
            self.logger.error(f"Failed to get node info: {e}")

    def on_meshtastic_message(self, packet, interface):
        self.logger.info(f"Received message from Meshtastic: {packet}")
        self.logger.debug(f"Message details - fromId: {packet.get('fromId')}, toId: {packet.get('toId')}, portnum: {packet.get('decoded', {}).get('portnum')}")
        self.thread_safe_queue.put(packet)

    def on_connection(self, interface, topic=pub.AUTO_TOPIC):
        self.logger.info(f"Connected to Meshtastic interface: {interface}")

    async def send_message(self, text: str, recipient: str) -> None:
        self.logger.info(f"Attempting to send message to Meshtastic: {text}")
        try:
            self.logger.debug(f"Sending message to Meshtastic with recipient: {recipient}")
            result = await asyncio.to_thread(self.interface.sendText, text, destinationId=recipient)
            self.logger.info(f"Message sent to Meshtastic: {text}")
            self.logger.debug(f"Send result: {result}")
        except Exception as e:
            self.logger.error(f"Error sending message to Meshtastic: {e}", exc_info=True)
            self.pending_messages.append(PendingMessage(text, recipient))

    async def send_node_info(self, node_info: Dict[str, Any]) -> None:
        node_id = node_info.get('user', {}).get('id', 'unknown')
        self.node_manager.update_node(node_id, {
            'name': node_info.get('user', {}).get('longName', 'unknown'),
            'shortName': node_info.get('user', {}).get('shortName', 'unknown'),
            'hwModel': node_info.get('user', {}).get('hwModel', 'unknown')
        })
        await self.message_queue.put({'type': 'node_info', 'text': self.node_manager.format_node_info(node_id)})

    async def send_bell(self, dest_id: str) -> None:
        try:
            await asyncio.to_thread(self.interface.sendText, "🔔", destinationId=dest_id)
            self.logger.info(f"Bell (text message) sent to node {dest_id}")
        except Exception as e:
            self.logger.error(f"Error sending bell to node {dest_id}: {e}")
            raise

    async def request_location(self, dest_id: str) -> None:
        try:
            await asyncio.to_thread(self.interface.sendText, "Please share your location", destinationId=dest_id)
            self.logger.info(f"Location request (text message) sent to node {dest_id}")
        except Exception as e:
            self.logger.error(f"Error requesting location from node {dest_id}: {e}")
            raise

    async def request_telemetry(self, dest_id: str) -> None:
        try:
            await asyncio.to_thread(self.interface.sendTelemetry)
            self.logger.info(f"Telemetry request sent to node {dest_id}")
        except Exception as e:
            self.logger.error(f"Error requesting telemetry from node {dest_id}: {e}")
            raise

    async def traceroute(self, dest_id: str) -> None:
        try:
            self.logger.info(f"Initiating traceroute to {dest_id}")
            await asyncio.to_thread(self.interface.sendText, f"!traceroute {dest_id}", destinationId=dest_id)
            self.logger.info(f"Traceroute request sent to {dest_id}")
        except Exception as e:
            self.logger.error(f"Error performing traceroute to node {dest_id}: {e}")
            raise

    async def process_pending_messages(self) -> None:
        while True:
            current_time = datetime.now()
            for message in self.pending_messages[:]:
                if (message.last_attempt is None or 
                    (current_time - message.last_attempt) > timedelta(seconds=self.retry_interval)):
                    if message.attempts < self.max_retries:
                        try:
                            await self.send_message(message.text, message.recipient)
                            self.pending_messages.remove(message)
                        except Exception:
                            message.attempts += 1
                            message.last_attempt = current_time
                    else:
                        self.logger.warning(f"Max retries reached for message: {message.text}")
                        self.pending_messages.remove(message)
            await asyncio.sleep(self.retry_interval)

    async def process_thread_safe_queue(self) -> None:
        while True:
            try:
                packet = self.thread_safe_queue.get_nowait()
                self.loop.call_soon_threadsafe(self.message_queue.put_nowait, packet)
            except queue.Empty:
                await asyncio.sleep(0.1)

    async def get_status(self) -> str:
        if not self.interface:
            return "Meshtastic interface not connected"
        try:
            node_info = await asyncio.to_thread(self.interface.getMyNodeInfo)
            return f"Connected to node: {node_info.get('user', {}).get('longName', 'Unknown')}\n" \
                   f"Battery level: {node_info.get('deviceMetrics', {}).get('batteryLevel', 'Unknown')}\n" \
                   f"Channel utilization: {node_info.get('deviceMetrics', {}).get('channelUtilization', 'Unknown')}"
        except Exception as e:
            return f"Error getting meshtastic status: {e}"

    async def close(self) -> None:
        if not self.is_setup:
            self.logger.info("Meshtastic interface was not set up, skipping close.")
            return
        try:
            await asyncio.to_thread(self.interface.close)
            pub.unsubscribe(self.on_meshtastic_message, "meshtastic.receive")
            pub.unsubscribe(self.on_connection, "meshtastic.connection.established")
        except Exception as e:
            self.logger.error(f"Error closing Meshtastic interface: {e}")
        self.logger.info("Meshtastic interface closed.")