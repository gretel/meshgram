import logging
import re
from typing import Any, Optional, List
from envyaml import EnvYAML

class ConfigManager:
    def __init__(self, config_path: str = 'config/config.yaml'):
        try:
            self.config = EnvYAML(config_path)
        except Exception as e:
            raise ValueError(f"Failed to load configuration from {config_path}: {e}")
        self.setup_logging()

    def get(self, key: str, default: Optional[Any] = None) -> Any:
        value = self.config.get(key, default)
        if value is None and default is None:
            raise KeyError(f"Configuration key '{key}' not found and no default value provided")
        return value

    def get_authorized_users(self) -> List[int]:
        users = self.get('telegram.authorized_users', [])
        return [int(user) for user in users if str(user).isdigit()]

    def setup_logging(self) -> None:
        log_level = self._parse_log_level(self.get('logging.level', 'INFO'))
        formatter = SensitiveFormatter('%(asctime)s %(levelname)s [%(name)s] %(message)s',)
        
        logging.basicConfig(
            level=log_level,
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler('meshgram.log')
            ]
        )
        
        for handler in logging.getLogger().handlers:
            handler.setFormatter(formatter)

        if self.get('logging.use_syslog', False):
            self._setup_syslog_handler()

    def _parse_log_level(self, level: Any) -> int:
        if isinstance(level, str):
            try:
                return getattr(logging, level.upper())
            except AttributeError:
                logging.warning(f"Invalid log level: {level}. Defaulting to INFO.")
                return logging.INFO
        elif isinstance(level, int):
            return level
        else:
            logging.warning(f"Invalid log level type: {type(level)}. Defaulting to INFO.")
            return logging.INFO

    def _setup_syslog_handler(self) -> None:
        try:
            syslog_handler = logging.handlers.SysLogHandler(
                address=(self.get('logging.syslog_host'), self.get('logging.syslog_port', 514)),
                socktype=logging.handlers.socket.SOCK_DGRAM if self.get('logging.syslog_protocol', 'udp') == 'udp' else logging.handlers.socket.SOCK_STREAM
            )
            syslog_handler.setFormatter(SensitiveFormatter('%(name)s - %(levelname)s - %(message)s'))
            logging.getLogger().addHandler(syslog_handler)
        except Exception as e:
            logging.error(f"Failed to set up syslog handler: {e}")

    def validate_config(self) -> None:
        required_keys = [
            'telegram.bot_token',
            'telegram.chat_id',
            'meshtastic.connection_type',
            'meshtastic.device',
        ]
        for key in required_keys:
            if not self.get(key):
                raise ValueError(f"Missing required configuration: {key}")

class SensitiveFormatter(logging.Formatter):
    def __init__(self, fmt: Optional[str] = None, datefmt: Optional[str] = None):
        super().__init__(fmt, datefmt)
        self.sensitive_patterns = [
            (re.compile(r'(bot\d+):(AAH[\w-]{34})'), r'\1:[REDACTED]'),
            (re.compile(r'(token=)([A-Za-z0-9-_]{35,})'), r'\1[REDACTED]'),
        ]

    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        for pattern, replacement in self.sensitive_patterns:
            message = pattern.sub(replacement, message)
        return message

def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)