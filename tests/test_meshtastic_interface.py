# tests/test_meshtastic_interface.py
import pytest
from unittest.mock import Mock, patch
from meshtastic_interface import MeshtasticInterface

@pytest.fixture
def meshtastic_interface():
    config = Mock()
    return MeshtasticInterface(config)

def test_send_message(meshtastic_interface):
    with patch.object(meshtastic_interface, 'interface') as mock_interface:
        asyncio.run(meshtastic_interface.send_message("test", "recipient"))
        mock_interface.sendText.assert_called_once_with("test", destinationId="recipient")