import pytest
from unittest.mock import AsyncMock, MagicMock
from meshtastic_interface import MeshtasticInterface
from config_manager import ConfigManager

@pytest.fixture
def mock_config():
    config = MagicMock(spec=ConfigManager)
    config.get.return_value = 'serial'
    return config

@pytest.mark.asyncio
async def test_meshtastic_interface_setup(mock_config):
    interface = MeshtasticInterface(mock_config)
    interface._create_interface = AsyncMock()
    interface._fetch_node_info = AsyncMock()

    await interface.setup()

    assert interface.is_setup == True
    interface._create_interface.assert_called_once()
    interface._fetch_node_info.assert_called_once()

@pytest.mark.asyncio
async def test_meshtastic_interface_send_message(mock_config):
    interface = MeshtasticInterface(mock_config)
    interface.interface = MagicMock()
    interface.interface.sendText = AsyncMock()

    await interface.send_message("Test message", "!4e19d9a4")

    interface.interface.sendText.assert_called_once_with("Test message", destinationId="!4e19d9a4")

# Add more tests for other methods...