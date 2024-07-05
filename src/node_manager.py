from __future__ import annotations

from typing import Dict, Any, Optional, List, Union, TypedDict
from datetime import datetime, timedelta
from telegram.helpers import escape_markdown

class NodeData(TypedDict):
    shortName: str
    longName: str
    hwModel: str
    batteryLevel: Optional[int]
    voltage: Optional[float]
    channelUtilization: Optional[float]
    airUtilTx: Optional[float]
    temperature: Optional[float]
    relativeHumidity: Optional[float]
    barometricPressure: Optional[float]
    gasResistance: Optional[float]
    current: Optional[float]
    latitude: Optional[float]
    longitude: Optional[float]
    last_updated: str
    last_position_update: Optional[str]
    routing: Dict[str, Any]
    neighbors: Dict[str, Any]
    sensor: Dict[str, Any]

class NodeManager:
    def __init__(self) -> None:
        self.nodes: Dict[str, NodeData] = {}
        self.node_history: Dict[str, List[NodeData]] = {}
        self.history_limit: int = 100

    def format_node_name(self, node_id: Union[str, int], short_name: str) -> str:
        numeric_id: int = (
            int(node_id[1:], 16) if isinstance(node_id, str) and node_id.startswith('!')
            else int(node_id) if isinstance(node_id, str)
            else node_id
        )
        return f'[{self.escape_value(node_id)} ({self.escape_value(short_name)})](https://meshtastic.liamcottle.net/?node_id={numeric_id})'

    def format_node_info(self, node_id: str) -> str:
        node = self.get_node(node_id)
        if not node:
            return f"ℹ️ No information available for node {self.escape_node_id(node_id)}"
        
        short_name = node.get('shortName', 'unknown')
        formatted_name = self.format_node_name(node_id, short_name)
        info = [f"🔷 Node {formatted_name}:"]
        emoji_map = {
            'name': '📛', 'longName': '📝', 'hwModel': '🖥️',
            'batteryLevel': '🔋', 'voltage': '⚡', 'channelUtilization': '📊',
            'airUtilTx': '📡', 'temperature': '🌡️', 'relativeHumidity': '💧',
            'barometricPressure': '🌪️', 'gasResistance': '💨', 'current': '⚡',
            'last_updated': '🕒'
        }
        
        for key, value in node.items():
            if key == 'last_updated':
                value = self._format_date(value)
            elif key in ['channelUtilization', 'airUtilTx']:
                value = self._format_percentage(value)
            elif key == 'shortName':
                continue  # Skip shortName as it's already included in the formatted name
            emoji = emoji_map.get(key, '🔹')
            info.append(f"{emoji} {self.escape_value(key.capitalize())}: {self.escape_value(str(value))}")
        
        return "\n".join(info)

    def _format_date(self, date_str: str) -> str:
        try:
            date = datetime.fromisoformat(date_str)
            return date.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return "Unknown"

    def _format_percentage(self, value: Any) -> str:
        match value:
            case int() | float():
                return f"{value:.2f}%"
            case _:
                return str(value)

    def update_node(self, node_id: str, data: Dict[str, Any]) -> None:
        if node_id not in self.nodes:
            self.nodes[node_id] = NodeData()
            self.node_history[node_id] = []
        
        self.nodes[node_id].update(data)
        self.nodes[node_id]['last_updated'] = datetime.now().isoformat()
        
        self.node_history[node_id].append(self.nodes[node_id].copy())
        if len(self.node_history[node_id]) > self.history_limit:
            self.node_history[node_id].pop(0)

    def get_node(self, node_id: str) -> Optional[NodeData]:
        return self.nodes.get(node_id)

    def get_all_nodes(self) -> Dict[str, NodeData]:
        return self.nodes

    def get_node_position(self, node_id: str) -> str:
        node = self.get_node(node_id)
        if not node:
            return f"📍 No position available for node {self.escape_node_id(node_id)}"
        
        latitude = node.get('latitude', 'N/A')
        longitude = node.get('longitude', 'N/A')
        last_position_update = node.get('last_position_update', 'N/A')

        return (
            f"📍 Position for node {self.escape_node_id(node_id)}:\n"
            f"🌎 Latitude: {self.escape_value(latitude)}\n"
            f"🌍 Longitude: {self.escape_value(longitude)}\n"
            f"🕒 Last updated: {self.escape_value(self._format_date(last_position_update) if last_position_update != 'N/A' else 'N/A')}"
        )

    def get_node_telemetry(self, node_id: str) -> str:
        node = self.get_node(node_id)
        if not node:
            return f"📊 No telemetry available for node {self.escape_node_id(node_id)}"
        
        battery_level = node.get('batteryLevel', 'N/A')
        battery_str = "PWR" if battery_level == 101 else f"{battery_level}%"
        air_util_tx = node.get('airUtilTx', 'N/A')
        air_util_tx_str = self._format_percentage(air_util_tx)
        channel_utilization = node.get('channelUtilization', 'N/A')
        channel_utilization_str = self._format_percentage(channel_utilization)
        uptime = node.get('uptimeSeconds', 'N/A')
        last_updated = node.get('last_updated', 'N/A')

        return (
            f"📊 Telemetry for node {self.escape_node_id(node_id)}:\n"
            f"🔋 Battery: {self.escape_value(battery_str)}\n"
            f"📡 Air Utilization TX: {self.escape_value(air_util_tx_str)}\n"
            f"📊 Channel Utilization: {self.escape_value(channel_utilization_str)}\n"
            f"⏱️ Uptime: {self.escape_value(str(uptime))} seconds\n"
            f"🕒 Last updated: {self.escape_value(self._format_date(last_updated) if last_updated != 'N/A' else 'N/A')}"
        )

    def escape_node_id(self, node_id: str) -> str:
        return escape_markdown(node_id, version=2)

    def escape_value(self, value: Any) -> str:
        # First, escape special Markdown characters
        escaped = escape_markdown(str(value), version=2)
        # Then, remove escaping for underscores and hyphens
        escaped = escaped.replace("\\_", "_").replace("\\-", "-")
        # Finally, remove escaping for periods (common in node IDs)
        escaped = escaped.replace("\\.", ".")
        return escaped

    def validate_node_id(self, node_id: str) -> bool:
        return len(node_id) == 8 and all(c in '0123456789abcdefABCDEF' for c in node_id)

    def update_node_telemetry(self, node_id: str, telemetry_data: Dict[str, Any]) -> None:
        self.update_node(node_id, telemetry_data)

    def update_node_position(self, node_id: str, position_data: Dict[str, Any]) -> None:
        lat = position_data.get('latitudeI')
        lon = position_data.get('longitudeI')
        if lat is not None and lon is not None:
            self.update_node(node_id, {
                'latitude': lat / 1e7,
                'longitude': lon / 1e7,
                'last_position_update': datetime.now().isoformat()
            })

    def get_inactive_nodes(self, timeout: int = 300) -> List[str]:
        now = datetime.now()
        return [
            node_id for node_id, node in self.nodes.items()
            if 'last_updated' in node and 
            (now - datetime.fromisoformat(node['last_updated'])) > timedelta(seconds=timeout)
        ]

    def remove_node(self, node_id: str) -> None:
        self.nodes.pop(node_id, None)
        self.node_history.pop(node_id, None)

    def update_node_routing(self, node_id: str, routing_info: Dict[str, Any]) -> None:
        self.update_node(node_id, {'routing': routing_info})

    def update_node_neighbors(self, node_id: str, neighbor_info: Dict[str, Any]) -> None:
        self.update_node(node_id, {'neighbors': neighbor_info})

    def update_node_sensor(self, node_id: str, sensor_data: Dict[str, Any]) -> None:
        self.update_node(node_id, {'sensor': sensor_data})

    def format_node_routing(self, node_id: str) -> str:
        node = self.get_node(node_id)
        if not node or 'routing' not in node:
            return f"🔀 No routing information available for node {self.escape_node_id(node_id)}"
        
        routing_info = node['routing']
        return (f"🔀 Routing information for node {self.escape_node_id(node_id)}:\n" + 
                "\n".join(f"  {self.escape_value(k)}: {self.escape_value(v)}" for k, v in routing_info.items()))

    def format_node_neighbors(self, node_id: str) -> str:
        node = self.get_node(node_id)
        if not node or 'neighbors' not in node:
            return f"👥 No neighbor information available for node {self.escape_node_id(node_id)}"
        
        neighbor_info = node['neighbors']
        return (f"👥 Neighbor information for node {self.escape_node_id(node_id)}:\n" + 
                "\n".join(f"  {self.escape_value(k)}: {self.escape_value(v)}" for k, v in neighbor_info.items()))

    def get_node_sensor_info(self, node_id: str) -> str:
        node = self.get_node(node_id)
        if not node or 'sensor' not in node:
            return f"🔬 No sensor information available for node {self.escape_node_id(node_id)}"
        
        sensor_data = node['sensor']
        return (f"🔬 Sensor information for node {self.escape_node_id(node_id)}:\n" + 
                "\n".join(f"  {self.escape_value(k)}: {self.escape_value(v)}" for k, v in sensor_data.items()))