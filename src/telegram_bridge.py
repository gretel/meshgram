import os
import sys
import logging
import asyncio
from typing import Dict, Any
from pathlib import Path
import time
import socket

import meshtastic
import meshtastic.serial_interface
import meshtastic.tcp_interface
from pubsub import pub
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from envyaml import EnvYAML
from logging.handlers import SysLogHandler

config = EnvYAML('config/config.yaml')

LOG_LEVEL = config['logging']['level']
logging.basicConfig(level=LOG_LEVEL, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

if 'syslog' in config:
    SYSLOG_HOST = config['syslog']['host']
    SYSLOG_PORT = config['syslog'].get('port', 514)
    syslog_handler = SysLogHandler(address=(SYSLOG_HOST, SYSLOG_PORT))
    syslog_handler.setLevel(LOG_LEVEL)
    logger.addHandler(syslog_handler)

logging.getLogger("meshtastic").setLevel(logging.WARNING)
logging.getLogger("aiogram").setLevel(logging.WARNING)

API_TOKEN = config['telegram']['bot_token']
CHAT_ID = config['telegram']['chat_id']
if not API_TOKEN:
    raise ValueError("No Telegram bot token provided. Set TELEGRAM_BOT_TOKEN in environment or config.yaml")
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

CONNECTION_TYPE = config['meshtastic']['connection_type']
if CONNECTION_TYPE == 'serial':
    MESHTASTIC_DEVICE = config['meshtastic']['device']
    interface = meshtastic.serial_interface.SerialInterface(devPath=MESHTASTIC_DEVICE)
elif CONNECTION_TYPE == 'tcp':
    MESHTASTIC_HOST = config['meshtastic']['host']
    MESHTASTIC_PORT = config['meshtastic']['port']
    interface = meshtastic.tcp_interface.TCPInterface(hostname=MESHTASTIC_HOST, port=MESHTASTIC_PORT)
else:
    raise ValueError("Invalid connection type. Must be 'serial' or 'tcp'")

chat_node_map: Dict[int, str] = {}

DEFAULT_NODE_ID = config['meshtastic']['default_node_id']

RATE_LIMIT = config['meshtastic']['rate_limit']
message_count = 0
last_reset_time = time.time()

message_queue = asyncio.Queue()

STATUS_INTERVAL = config['bridge']['status_interval']

loop = None

def handle_meshtastic_message(packet, interface) -> None:
    global message_count, last_reset_time
    
    try:
        current_time = time.time()
        if current_time - last_reset_time >= 60:
            message_count = 0
            last_reset_time = current_time

        if message_count >= RATE_LIMIT:
            logger.warning("Rate limit exceeded. Dropping message.")
            return

        sender = packet.get('fromId', 'Unknown')
        message = packet.get('decoded', {}).get('text')
        
        if message is None:
            logger.debug(f"Received packet from {sender} without text content")
            return

        logger.info(f"Received Meshtastic message from {sender}: {message}")

        asyncio.run_coroutine_threadsafe(process_meshtastic_message(sender, message), loop)
        message_count += 1
    except Exception as e:
        logger.error(f"Error handling Meshtastic message: {e}", exc_info=True)

async def process_meshtastic_message(sender, message) -> None:
    await message_queue.put((CHAT_ID, f"Message from Meshtastic node {sender}: {message}"))

async def process_message_queue() -> None:
    while True:
        try:
            chat_id, message = await message_queue.get()
            await bot.send_message(chat_id, message)
            message_queue.task_done()
        except Exception as e:
            logger.error(f"Error sending message to Telegram: {e}", exc_info=True)
        await asyncio.sleep(0.1)

@dp.message(Command("connect"))
async def connect_node(message: types.Message) -> None:
    try:
        command_parts = message.text.split()
        if len(command_parts) > 1:
            node_id = command_parts[1]
            chat_node_map[message.chat.id] = node_id
            await message.reply(f"Connected to Meshtastic node: {node_id}")
        else:
            chat_node_map[message.chat.id] = None
            await message.reply(f"Connected to default Meshtastic node {DEFAULT_NODE_ID}")
        logger.info(f"Chat {message.chat.id} connected to Meshtastic node {chat_node_map[message.chat.id] or DEFAULT_NODE_ID}")
    except Exception as e:
        logger.error(f"Error connecting to node: {e}", exc_info=True)
        await message.reply("Failed to connect to Meshtastic node. Please try again.")

@dp.message()
async def process_telegram_message(message: types.Message) -> None:
    node_id = chat_node_map.get(message.chat.id, DEFAULT_NODE_ID)
    try:
        interface.sendText(message.text, destinationId=node_id)
        await message.reply(f"Message sent to Meshtastic node {node_id}.")
        logger.info(f"Message sent to Meshtastic node {node_id} from chat {message.chat.id}")
    except Exception as e:
        logger.error(f"Error sending message to Meshtastic: {e}", exc_info=True)
        await message.reply("Failed to send message to Meshtastic node.")

async def send_status_update() -> None:
    while True:
        try:
            status_message = f"Meshtastic-Telegram bridge is active. Connected to {CONNECTION_TYPE} interface."
            await bot.send_message(CHAT_ID, status_message)
            logger.info("Sent status update")
        except Exception as e:
            logger.error(f"Error sending status update: {e}", exc_info=True)
        await asyncio.sleep(STATUS_INTERVAL)

async def main() -> None:
    global loop
    loop = asyncio.get_running_loop()
    
    pub.subscribe(handle_meshtastic_message, "meshtastic.receive")
    
    asyncio.create_task(process_message_queue())
    asyncio.create_task(send_status_update())
    
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())