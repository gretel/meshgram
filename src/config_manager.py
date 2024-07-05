import logging
import re
from typing import Any, Optional, List, Dict
from envyaml import EnvYAML

class ConfigManager:
    def __init__(self, config_path: str = 'config/config.yaml'):
        try:
            self.config: Dict[str, Any] = EnvYAML(config_path)
        except Exception as e:
            raise ValueError(f"Failed to load configuration from {config_path}: {e}")
        self._setup_logging()

    def get(self, key: str, default: Optional[Any] = None) -> Any:
        value = self.config.get(key, default)
        if value is None and default is None:
            raise KeyError(f"Configuration key '{key}' not found and no default value provided")
        return value

    def get_authorized_users(self) -> List[int]:
        users = self.get('telegram.authorized_users', [])
        return [int(user) for user in users if str(user).isdigit()]

    def _setup_logging(self) -> None:
        log_level = self._parse_log_level(self.get('logging.level', 'INFO'))
        log_level_telegram = self._parse_log_level(self.get('logging.level_telegram', 'INFO'))
        log_level_httpx = self._parse_log_level(self.get('logging.level_telegram', 'WARN'))

        formatter = SensitiveFormatter('%(asctime)s %(levelname)s %(name)s - %(message)s')
        
        handlers = [logging.StreamHandler()]
        if self.get('logging.file_log', False):
            handlers.append(logging.FileHandler(self.get('logging.file_path', 'meshgram.log')))
        
        logging.basicConfig(level=log_level, handlers=handlers, format='%(asctime)s %(levelname)s %(name)s - %(message)s')
        
        for handler in logging.root.handlers:
            handler.setFormatter(formatter)

        logging.getLogger('httpx').setLevel(log_level_httpx)
        logging.getLogger('telegram').setLevel(log_level_telegram)

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
            from logging.handlers import SysLogHandler
            syslog_handler = SysLogHandler(
                address=(self.get('logging.syslog_host'), self.get('logging.syslog_port', 514)),
                socktype=SysLogHandler.UDP_SOCKET if self.get('logging.syslog_protocol', 'udp').lower() == 'udp' else SysLogHandler.TCP_SOCKET
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
        missing_keys = [key for key in required_keys if not self.get(key)]
        if missing_keys:
            raise ValueError(f"Missing required configuration: {', '.join(missing_keys)}")

class SensitiveFormatter(logging.Formatter):
    def __init__(self, fmt: Optional[str] = None, datefmt: Optional[str] = None):
        super().__init__(fmt, datefmt)
        self.sensitive_patterns = [
            (re.compile(r'(https://api\.telegram\.org/bot)([A-Za-z0-9:_-]{35,})(/\w+)'), r'\1[redacted]\3')
        ]

    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        for pattern, replacement in self.sensitive_patterns:
            message = pattern.sub(replacement, message)
        return message

def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)