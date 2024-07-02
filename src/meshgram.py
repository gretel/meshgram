import argparse
import asyncio
from typing import Optional, List
from meshtastic_interface import MeshtasticInterface
from telegram_interface import TelegramInterface
from message_processor import MessageProcessor
from config_manager import ConfigManager, get_logger
from asyncio import Task

class Meshgram:
    def __init__(self, config: ConfigManager) -> None:
        self.config: ConfigManager = config
        self.logger = get_logger(__name__)
        self.meshtastic: Optional[MeshtasticInterface] = None
        self.telegram: Optional[TelegramInterface] = None
        self.message_processor: Optional[MessageProcessor] = None
        self.tasks: List[Task] = []

    async def setup(self) -> None:
        self.logger.info("Setting up meshgram...")
        try:
            self.meshtastic = MeshtasticInterface(self.config)
            await self.meshtastic.setup()
            
            self.telegram = TelegramInterface(self.config)
            await self.telegram.setup()
            
            self.message_processor = MessageProcessor(self.meshtastic, self.telegram, self.config)
            self.logger.info("Meshgram setup complete.")
        except Exception as e:
            self.logger.error(f"Error during setup: {e}")
            await self.shutdown()
            raise

    async def run(self) -> None:
        try:
            await self.setup()
        except Exception as e:
            self.logger.error(f"Failed to set up Meshgram: {e}")
            return

        self.logger.info("Meshgram is running ヽ(´▽`)/")
        self.tasks = [
            asyncio.create_task(self.message_processor.process_messages()),
            asyncio.create_task(self.meshtastic.process_thread_safe_queue()),
            asyncio.create_task(self.meshtastic.process_pending_messages()),
            asyncio.create_task(self.telegram.start_polling()),
            asyncio.create_task(self.message_processor.check_heartbeats())
        ]
        try:
            await asyncio.gather(*self.tasks)
        except asyncio.CancelledError:
            self.logger.info("Received cancellation signal.")
        except Exception as e:
            self.logger.error(f"An error occurred: {e}", exc_info=True)
        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        self.logger.info("Shutting down meshgram...")
        for task in self.tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        if self.meshtastic:
            await self.meshtastic.close()
        if self.telegram:
            await self.telegram.close()
        if self.message_processor:
            if hasattr(self.message_processor, 'close'):
                await self.message_processor.close()
            else:
                self.logger.warning("MessageProcessor does not have a close method.")
        self.logger.info("Meshgram shutdown complete.")

async def main() -> None:
    parser = argparse.ArgumentParser(description='Meshgram: Meshtastic-Telegram Bridge')
    parser.add_argument('-c', '--config', default='config/config.yaml', help='Path to configuration file')
    parser.add_argument('--version', action='version', version='%(prog)s 1.0.0')
    args = parser.parse_args()

    config = ConfigManager(args.config)
    config.setup_logging()
    logger = get_logger(__name__)

    app = Meshgram(config)
    try:
        await app.run()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt. Shutting down gracefully...")
    except Exception as e:
        logger.error(f"Unhandled exception: {e}", exc_info=True)
    finally:
        await app.shutdown()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown complete.")
