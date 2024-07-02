from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

class NodeManager:
    def __init__(self):
        self.nodes: Dict[str, Dict[str, Any]] = {}
        self.node_history: Dict[str, List[Dict[str, Any]]] = {}
        self.history_limit = 100

    def update_node(self, node_id: str, data: Dict[str, Any]) -> None:
        if node_id not in self.nodes:
            self.nodes[node_id] = {}
            self.node_history[node_id] = []
        
        self.nodes[node_id].update(data)
        self.nodes[node_id]['last_updated'] = datetime.now().isoformat()
        
        self.node_history[node_id].append(self.nodes[node_id].copy())
        if len(self.node_history[node_id]) > self.history_limit:
            self.node_history[node_id].pop(0)

    def get_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        return self.nodes.get(node_id)

    def get_all_nodes(self) -> Dict[str, Dict[str, Any]]:
        return self.nodes

    def get_node_history(self, node_id: str) -> List[Dict[str, Any]]:
        return self.node_history.get(node_id, [])

    def format_node_info(self, node_id: str) -> str:
        node = self.get_node(node_id)
        if not node:
            return f"ℹ️ No information available for node {node_id}"
        info = [f"🔷 Discovered Node ID: {node_id}"]
        for key, value in node.items():
            if key != 'last_updated':
                emoji = {
                    'name': '📛', 'shortName': '🏷️', 'hwModel': '🖥️',
                    'batteryLevel': '🔋', 'voltage': '⚡', 'channelUtilization': '📊',
                    'airUtilTx': '📡', 'temperature': '🌡️', 'relativeHumidity': '💧',
                    'barometricPressure': '🌪️', 'gasResistance': '💨', 'current': '⚡'
                }.get(key, '🔹')
                info.append(f"{emoji} {key.capitalize()}: {value}")
        info.append(f"🕒 Last updated: {node.get('last_updated', 'Unknown')}")
        return "\n".join(info)
        
    def get_node_telemetry(self, node_id: str) -> str:
        node = self.get_node(node_id)
        if not node:
            return f"No telemetry available for node {node_id}"
        air_util_tx = node.get('airUtilTx', 'Unknown')
        air_util_tx_str = f"{air_util_tx:.2f}%" if isinstance(air_util_tx, (int, float)) else air_util_tx
        return (f"📊 Telemetry for node {node_id}:\n"
                f"• Battery: {node.get('batteryLevel', 'Unknown')}%\n"
                f"• Air Utilization TX: {air_util_tx_str}\n"
                f"• Uptime: {node.get('uptimeSeconds', 'Unknown')} seconds\n"
                f"• Last updated: {node.get('last_updated', 'Unknown')}")

    def get_node_position(self, node_id: str) -> str:
        node = self.get_node(node_id)
        if not node:
            return f"No position available for node {node_id}"
        return (f"📍 Position for node {node_id}:\n"
                f"• Latitude: {node.get('latitude', 'Unknown')}\n"
                f"• Longitude: {node.get('longitude', 'Unknown')}\n"
                f"• Last updated: {node.get('last_position_update', 'Unknown')}")

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