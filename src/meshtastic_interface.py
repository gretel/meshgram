from __future__ import annotations

import asyncio
import queue
from typing import Dict, Any, Optional, Union, List, TypedDict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from meshtastic import tcp_interface, serial_interface
from meshtastic.serial_interface import SerialInterface
from meshtastic.tcp_interface import TCPInterface
from pubsub import pub
from config_manager import ConfigManager, get_logger
from node_manager import NodeManager

class DeviceMetrics(TypedDict):
    batteryLevel: int
    voltage: float
    channelUtilization: float
    airUtilTx: float

class NodeInfo(TypedDict):
    user: Dict[str, Any]
    deviceMetrics: DeviceMetrics

@dataclass
class PendingMessage:
    text: str
    recipient: str
    attempts: int = 0
    last_attempt: Optional[datetime] = field(default=None)

class MeshtasticInterface:
    def __init__(self, config: ConfigManager) -> None:
        self.config: ConfigManager = config
        self.logger = get_logger(__name__)
        self.interface: Optional[Union[SerialInterface, TCPInterface]] = None
        self.message_queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        self.thread_safe_queue: queue.Queue[Dict[str, Any]] = queue.Queue()
        self.loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        self.pending_messages: List[PendingMessage] = []
        self.last_telemetry: Dict[str, Any] = {}
        self.max_retries: int = 3
        self.retry_interval: int = 60
        self.node_manager: NodeManager = NodeManager()
        self.is_setup: bool = False
        self.is_closing: bool = False

    async def setup(self) -> None:
        self.logger.info("Setting up meshtastic interface...")
        try:
            self.interface = await self._create_interface()
            pub.subscribe(self.on_meshtastic_message, "meshtastic.receive")
            await self._fetch_node_info()
            self.is_setup = True
            self.logger.info("Meshtastic interface setup complete.")
        except Exception as e:
            self.logger.error(f"Failed to set up Meshtastic interface: {e=}", exc_info=True)
            raise

    async def _create_interface(self) -> Union[SerialInterface, TCPInterface]:
        connection_type: str = self.config.get('meshtastic.connection_type', 'serial')
        device: str = self.config.get('meshtastic.device')
        if not device:
            raise ValueError("Meshtastic device is not configured in the YAML file.")
        
        match connection_type:
            case 'serial':
                return await asyncio.to_thread(serial_interface.SerialInterface, device)
            case 'tcp':
                host, port = device.split(':')
                return await asyncio.to_thread(tcp_interface.TCPInterface, hostname=host, port=int(port))
            case _:
                raise ValueError(f"Unsupported connection type: {connection_type}")

    async def _fetch_node_info(self) -> None:
        try:
            my_node_info: NodeInfo = await asyncio.to_thread(self.interface.getMyNodeInfo)
            node_id = my_node_info['user'].get('id')
            if node_id:
                self.logger.info(f"Received info on our node: {my_node_info=}")
            else:
                self.logger.error(f"Received node info without a node ID: {my_node_info=}")
        except Exception as e:
            self.logger.error(f"Failed to get node info: {e=}", exc_info=True)

    def on_meshtastic_message(self, packet: Dict[str, Any], interface: Any) -> None:
        self.logger.debug(f"Message details - {packet.get('fromId')=}, {packet.get('toId')=}, {packet.get('decoded', {}).get('portnum')=}")
        if packet.get('decoded', {}).get('portnum') == 'ROUTING_APP':
            self.handle_ack(packet)
        else:
            self.thread_safe_queue.put(packet)

    def handle_ack(self, packet: Dict[str, Any]) -> None:
        ack_data: Dict[str, Any] = {
            'type': 'ack',
            'from': packet.get('fromId'),
            'to': packet.get('toId'),
            'message_id': packet.get('id')
        }
        self.loop.call_soon_threadsafe(self.message_queue.put_nowait, ack_data)

    async def send_reaction(self, emoji: str, message_id: str) -> None:
        try:
            await asyncio.to_thread(self.interface.sendReaction, emoji, messageId=message_id)
            self.logger.info(f"Reaction {emoji} sent for message {message_id}")
        except Exception as e:
            self.logger.error(f"Error sending reaction to Meshtastic: {e=}", exc_info=True)

    async def send_message(self, text: str, recipient: str) -> None:
        if not text or not recipient:
            raise ValueError("Text and recipient must not be empty")
        if len(text) > 230:  # Meshtastic message size limit
            raise ValueError("Message too long")

        self.logger.info(f"Attempting to send message to Meshtastic: {text=}")
        try:
            self.logger.debug(f"Sending message to Meshtastic with {recipient=}")
            result = await asyncio.to_thread(self.interface.sendText, text, destinationId=recipient)
            self.logger.info(f"Message sent to Meshtastic: {text=}")
            self.logger.debug(f"{result=}")
        except Exception as e:
            self.logger.error(f"Error sending message to Meshtastic: {e=}", exc_info=True)
            self.pending_messages.append(PendingMessage(text, recipient))

    async def send_bell(self, dest_id: str) -> None:
        if not dest_id:
            raise ValueError("Destination ID must not be empty")

        try:
            await asyncio.to_thread(self.interface.sendText, "🔔", destinationId=dest_id)
            self.logger.info(f"Bell (text message) sent to node {dest_id}")
        except Exception as e:
            self.logger.error(f"Error sending bell to node {dest_id}: {e}", exc_info=True)
            raise

    async def process_pending_messages(self) -> None:
        while True:
            current_time = datetime.now()
            for message in self.pending_messages[:]:
                if (message.last_attempt is None or (current_time - message.last_attempt) > timedelta(seconds=self.retry_interval)):
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
                await self.message_queue.put(packet)
            except queue.Empty:
                await asyncio.sleep(0.1)

    async def get_status(self) -> str:
        if not self.interface:
            return "Meshtastic interface not connected"
        try:
            node_info = await asyncio.to_thread(self.interface.getMyNodeInfo)
            battery_level = node_info.get('deviceMetrics', {}).get('batteryLevel', 'N/A')
            battery_str = "PWR" if battery_level == 101 else f"{battery_level}%"
            air_util_tx = node_info.get('deviceMetrics', {}).get('airUtilTx', 'N/A')
            air_util_tx_str = f"{air_util_tx:.2f}%" if isinstance(air_util_tx, (int, float)) else air_util_tx
            return (
                f"Node: {node_info.get('user', {}).get('longName', 'N/A')}\n"
                f"Battery: {battery_str}\n"
                f"Air Utilization TX: {air_util_tx_str}"
            )
        except Exception as e:
            self.logger.error(f"Error getting meshtastic status: {e}", exc_info=True)
            return f"Error getting meshtastic status: {e}"

    async def close(self) -> None:
        if self.is_closing:
            self.logger.info("Meshtastic interface is already closing, skipping.")
            return

        self.is_closing = True
        if not self.is_setup:
            self.logger.info("Meshtastic interface was not set up, skipping close.")
            return
        try:
            if self.interface:
                await asyncio.to_thread(self.interface.close)
            pub.unsubscribe(self.on_meshtastic_message, "meshtastic.receive")
        except Exception as e:
            self.logger.error(f"Error closing Meshtastic interface: {e}", exc_info=True)
        finally:
            self.is_setup = False
            self.is_closing = False
            self.logger.info("Meshtastic interface closed.")

    async def reconnect(self) -> None:
        self.logger.info("Attempting to reconnect to Meshtastic...")
        try:
            if self.interface:
                await asyncio.to_thread(self.interface.close)
            self.interface = await self._create_interface()
            self.logger.info("Reconnected to Meshtastic successfully.")
        except Exception as e:
            self.logger.error(f"Failed to reconnect to Meshtastic: {e}", exc_info=True)

    async def periodic_health_check(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self.interface.ping)
            except Exception as e:
                self.logger.error(f"Health check failed: {e}", exc_info=True)
                await self.reconnect()
            await asyncio.sleep(60)  # Check every minute

    def start_background_tasks(self) -> None:
        asyncio.create_task(self.process_pending_messages())
        asyncio.create_task(self.process_thread_safe_queue())
        asyncio.create_task(self.periodic_health_check())
