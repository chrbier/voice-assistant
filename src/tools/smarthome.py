"""
Smart Home Tool for ioBroker integration.
Controls devices via ioBroker Simple API.
Uses Alexa2 Smart-Home-Devices for reliable device discovery.
"""

import logging
import requests
from typing import Any, Callable, Optional
from src.config import config

logger = logging.getLogger(__name__)


class SmartHomeTool:
    """
    Smart Home control via ioBroker Simple API.
    Uses Alexa2 Smart-Home-Devices for reliable device discovery.
    - Blinds: Blind-Lift-rangeValue (0-100)
    - Lights/Switches: Powerstate (true/false)
    """
    
    ALEXA_DEVICES_PREFIX = "alexa2.0.Smart-Home-Devices"
    
    def __init__(self):
        self.base_url = f"http://{config.smarthome.iobroker_host}:{config.smarthome.iobroker_port}"
        self._timeout = 5  # seconds
        self._devices = {}  # name -> device info
    
    def _get_device_name(self, uuid: str) -> Optional[str]:
        """Get device name by fetching the channel object directly."""
        try:
            obj_id = f"{self.ALEXA_DEVICES_PREFIX}.{uuid}"
            # Use /get/ endpoint (not /getObject/)
            response = requests.get(
                f"{self.base_url}/get/{obj_id}",
                timeout=self._timeout
            )
            if response.status_code == 200:
                obj_data = response.json()
                # /get/ returns object with 'common' key
                name = obj_data.get('common', {}).get('name', '')
                if isinstance(name, dict):
                    name = name.get('de', name.get('en', str(name)))
                if name:
                    logger.debug(f"Gerätename für {uuid}: {name}")
                    return name
        except Exception as e:
            logger.debug(f"Konnte Namen für {uuid} nicht abrufen: {e}")
        return None
    
    def _load_alexa_devices(self) -> None:
        """Load all devices from Alexa2 Smart-Home-Devices."""
        try:
            response = requests.get(
                f"{self.base_url}/objects",
                params={"pattern": f"{self.ALEXA_DEVICES_PREFIX}.*"},
                timeout=self._timeout
            )
            if response.status_code != 200:
                logger.warning(f"Fehler beim Abrufen der Alexa-Geräte: Status {response.status_code}")
                return
            
            objects = response.json()
            logger.debug(f"Alexa2 liefert {len(objects)} Objekte")
            
            # Collect all device UUIDs and their states
            # Structure: alexa2.0.Smart-Home-Devices.{UUID}.{stateName}
            device_states = {}  # UUID -> {state_name: obj_id}
            device_names = {}   # UUID -> name (from folder/device object)
            
            for obj_id, obj_data in objects.items():
                # Skip system states (deleteAll, discoverDevices)
                if obj_id.endswith('.deleteAll') or obj_id.endswith('.discoverDevices'):
                    continue
                
                # Extract UUID from path
                parts = obj_id.split('.')
                if len(parts) < 4:
                    continue
                
                # alexa2.0.Smart-Home-Devices.UUID... 
                uuid = parts[3]
                
                # Skip if UUID looks like a system state
                if uuid in ['deleteAll', 'discoverDevices']:
                    continue
                
                obj_type = obj_data.get('type', '')
                common = obj_data.get('common', {})
                
                # If this is a folder or device object, get the name
                if obj_type in ['folder', 'device', 'channel']:
                    name = common.get('name', '')
                    if isinstance(name, dict):
                        name = name.get('de', name.get('en', str(name)))
                    if name and uuid not in device_names:
                        device_names[uuid] = name
                
                # If this is a state, collect it
                if obj_type == 'state' and len(parts) >= 5:
                    state_name = parts[4]  # e.g., powerState, rangeValue, etc.
                    if uuid not in device_states:
                        device_states[uuid] = {}
                    device_states[uuid][state_name] = obj_id
            
            # Now build device list from collected data
            for uuid, states in device_states.items():
                # Get device name - try cached first, then fetch individually
                name = device_names.get(uuid)
                if not name:
                    name = self._get_device_name(uuid)
                if not name:
                    name = uuid  # Fallback to UUID
                
                # Determine device type and relevant states
                device_type = 'unknown'
                blind_state = None
                power_state = None
                brightness_state = None
                
                # Check for blinds (Blind-Lift-rangeValue, percentage, etc.)
                for state_name in ['Blind-Lift-rangeValue', 'rangeValue', 'percentage']:
                    if state_name in states:
                        device_type = 'blind'
                        blind_state = states[state_name]
                        break
                
                # Check for power state (powerState - lowercase!)
                for state_name in ['powerState', 'Powerstate', 'power']:
                    if state_name in states:
                        if device_type == 'unknown':
                            device_type = 'switch'
                        power_state = states[state_name]
                        break
                
                # Check for brightness
                for state_name in ['brightness', 'Brightness', 'dimmer', 'level']:
                    if state_name in states:
                        device_type = 'dimmer'
                        brightness_state = states[state_name]
                        break
                
                if device_type != 'unknown':
                    self._devices[name.lower()] = {
                        'name': name,
                        'id': f"{self.ALEXA_DEVICES_PREFIX}.{uuid}",
                        'uuid': uuid,
                        'type': device_type,
                        'blind_state': blind_state,
                        'power_state': power_state,
                        'brightness_state': brightness_state,
                        'all_states': states  # Keep all states for debugging
                    }
            
            logger.info(f"✓ {len(self._devices)} Alexa Smart-Home Geräte geladen")
            
            # Log device types
            blinds = [d['name'] for d in self._devices.values() if d['type'] == 'blind']
            switches = [d['name'] for d in self._devices.values() if d['type'] in ['switch', 'dimmer']]
            if blinds:
                logger.info(f"  Rolladen: {', '.join(blinds[:5])}{'...' if len(blinds) > 5 else ''}")
            if switches:
                logger.info(f"  Lichter/Schalter: {', '.join(switches[:5])}{'...' if len(switches) > 5 else ''}")
            
            # Debug: log all found devices with their states
            for name, device in self._devices.items():
                logger.debug(f"  Gerät '{device['name']}' ({device['type']}): {list(device['all_states'].keys())}")
            
        except Exception as e:
            logger.warning(f"Fehler beim Laden der Alexa-Geräte: {e}")
    
    def _find_device(self, device_name: str, device_type: Optional[str] = None) -> Optional[dict]:
        """
        Find a device by name (fuzzy match).
        Returns device info dict or None.
        """
        device_name_lower = device_name.lower()
        
        # Direct match
        if device_name_lower in self._devices:
            device = self._devices[device_name_lower]
            if device_type is None or device['type'] == device_type:
                return device
        
        # Partial match
        for name, device in self._devices.items():
            if device_type and device['type'] != device_type:
                continue
            
            # Check if search term is in device name or vice versa
            if device_name_lower in name or name in device_name_lower:
                logger.info(f"Gerät gefunden: {device['name']} ({device['type']})")
                return device
        
        # Word-by-word match (for "Wohnzimmer Rollo" matching "Rollo Wohnzimmer")
        search_words = device_name_lower.split()
        for name, device in self._devices.items():
            if device_type and device['type'] != device_type:
                continue
            
            # Check if all search words are in the device name
            if all(word in name for word in search_words):
                logger.info(f"Gerät gefunden: {device['name']} ({device['type']})")
                return device
        
        return None
    
    def initialize(self) -> None:
        """Test connection to ioBroker and load Alexa devices."""
        try:
            response = requests.get(f"{self.base_url}/getPlainValue/system.adapter.admin.0.alive", timeout=self._timeout)
            if response.status_code == 200:
                logger.info(f"✓ ioBroker verbunden: {self.base_url}")
                # Load Alexa Smart-Home devices
                self._load_alexa_devices()
            else:
                logger.warning(f"ioBroker antwortet mit Status {response.status_code}")
        except requests.RequestException as e:
            logger.error(f"ioBroker nicht erreichbar: {e}")
            raise ConnectionError(f"Kann ioBroker nicht erreichen: {self.base_url}")
    
    def _get_state(self, object_id: str) -> Any:
        """Get current state of an object."""
        try:
            response = requests.get(f"{self.base_url}/getPlainValue/{object_id}", timeout=self._timeout)
            if response.status_code == 200:
                return response.text.strip()
            return None
        except requests.RequestException as e:
            logger.error(f"Fehler beim Lesen von {object_id}: {e}")
            return None
    
    def _set_state(self, object_id: str, value: Any) -> bool:
        """Set state of an object."""
        try:
            # Convert Python bool to lowercase string for ioBroker
            if isinstance(value, bool):
                value_str = "true" if value else "false"
            else:
                value_str = str(value)
            
            response = requests.get(
                f"{self.base_url}/set/{object_id}",
                params={"value": value_str},
                timeout=self._timeout
            )
            success = response.status_code == 200
            if success:
                logger.info(f"✓ {object_id} = {value_str}")
            else:
                logger.error(f"Fehler beim Setzen von {object_id}: Status {response.status_code}")
            return success
        except requests.RequestException as e:
            logger.error(f"Fehler beim Setzen von {object_id}: {e}")
            return False
    
    # === Tool Functions for Gemini ===
    
    def turn_on_device(self, device_name: str) -> str:
        """
        Turn on a device (light, switch, plug).
        
        Args:
            device_name: Name of the device to turn on
            
        Returns:
            Status message
        """
        logger.info(f"Schalte '{device_name}' ein...")
        
        device = self._find_device(device_name)
        if not device:
            return f"Gerät '{device_name}' nicht gefunden."
        
        # Use Powerstate for lights/switches
        if device.get('power_state'):
            if self._set_state(device['power_state'], True):
                return f"'{device['name']}' wurde eingeschaltet."
        
        return f"Konnte '{device_name}' nicht einschalten."
    
    def turn_off_device(self, device_name: str) -> str:
        """
        Turn off a device (light, switch, plug).
        
        Args:
            device_name: Name of the device to turn off
            
        Returns:
            Status message
        """
        logger.info(f"Schalte '{device_name}' aus...")
        
        device = self._find_device(device_name)
        if not device:
            return f"Gerät '{device_name}' nicht gefunden."
        
        # Use Powerstate for lights/switches
        if device.get('power_state'):
            if self._set_state(device['power_state'], False):
                return f"'{device['name']}' wurde ausgeschaltet."
        
        return f"Konnte '{device_name}' nicht ausschalten."
    
    def set_brightness(self, device_name: str, brightness: int) -> str:
        """
        Set brightness of a dimmable light.
        
        Args:
            device_name: Name of the light
            brightness: Brightness level 0-100
            
        Returns:
            Status message
        """
        logger.info(f"Setze Helligkeit von '{device_name}' auf {brightness}%...")
        
        brightness = max(0, min(100, brightness))
        
        device = self._find_device(device_name)
        if not device:
            return f"Gerät '{device_name}' nicht gefunden."
        
        # Use brightness state if available
        if device.get('brightness_state'):
            if self._set_state(device['brightness_state'], brightness):
                return f"Helligkeit von '{device['name']}' auf {brightness}% gesetzt."
        
        return f"Konnte Helligkeit von '{device_name}' nicht setzen. Gerät nicht dimmbar?"
    
    def set_color(self, device_name: str, color: str) -> str:
        """
        Set color of an RGB light.
        
        Args:
            device_name: Name of the light
            color: Color name (rot, grün, blau, gelb, weiß, etc.) or hex code
            
        Returns:
            Status message
        """
        logger.info(f"Setze Farbe von '{device_name}' auf {color}...")
        
        # Color name to hex mapping
        color_map = {
            'rot': '#FF0000', 'red': '#FF0000',
            'grün': '#00FF00', 'green': '#00FF00',
            'blau': '#0000FF', 'blue': '#0000FF',
            'gelb': '#FFFF00', 'yellow': '#FFFF00',
            'orange': '#FFA500',
            'lila': '#800080', 'purple': '#800080',
            'pink': '#FFC0CB', 'rosa': '#FFC0CB',
            'weiß': '#FFFFFF', 'white': '#FFFFFF',
            'warmweiß': '#FFE4B5', 'warm white': '#FFE4B5',
            'kaltweiß': '#F0F8FF', 'cool white': '#F0F8FF',
        }
        
        hex_color = color_map.get(color.lower(), color)
        
        matches = self._find_device(device_name)
        if not matches:
            return f"Gerät '{device_name}' nicht gefunden."
        
        for match in matches:
            obj_id = match['id']
            for suffix in ['.color', '.COLOR', '.rgb', '.RGB', '.hex']:
                state_id = obj_id + suffix
                if self._set_state(state_id, hex_color):
                    return f"Farbe von '{match['name']}' auf {color} gesetzt."
        
        return f"Konnte Farbe von '{device_name}' nicht setzen. Keine RGB-Lampe?"
    
    def set_temperature(self, device_name: str, temperature: float) -> str:
        """
        Set target temperature of a thermostat.
        
        Args:
            device_name: Name of the thermostat/room
            temperature: Target temperature in Celsius
            
        Returns:
            Status message
        """
        logger.info(f"Setze Temperatur von '{device_name}' auf {temperature}°C...")
        
        temperature = max(5, min(30, temperature))
        
        # First try room+function based search
        matches = self._find_device_by_room_and_function(device_name, 'thermostat')
        
        if matches:
            for match in matches:
                obj_id = match['id']
                for suffix in ['.setpoint', '.SETPOINT', '.target', '.TARGET', '.set_temperature', '']:
                    state_id = obj_id + suffix if suffix else obj_id
                    if self._set_state(state_id, temperature):
                        return f"Temperatur von '{match.get('name', device_name)}' auf {temperature}°C gesetzt."
        
        # Fallback to general search
        matches = self._find_device(device_name)
        if not matches:
            return f"Thermostat '{device_name}' nicht gefunden."
        
        for match in matches:
            obj_id = match['id']
            for suffix in ['.setpoint', '.SETPOINT', '.target', '.TARGET', '.set_temperature']:
                state_id = obj_id + suffix
                if self._set_state(state_id, temperature):
                    return f"Temperatur von '{match['name']}' auf {temperature}°C gesetzt."
        
        return f"Konnte Temperatur von '{device_name}' nicht setzen."
    
    def get_temperature(self, device_name: str) -> str:
        """
        Get current temperature from a sensor or thermostat.
        
        Args:
            device_name: Name of the sensor/thermostat/room
            
        Returns:
            Temperature reading
        """
        logger.info(f"Lese Temperatur von '{device_name}'...")
        
        matches = self._find_device(device_name)
        if not matches:
            return f"Temperatursensor '{device_name}' nicht gefunden."
        
        for match in matches:
            obj_id = match['id']
            for suffix in ['.temperature', '.TEMPERATURE', '.actual', '.ACTUAL', '', '.temp']:
                state_id = obj_id + suffix if suffix else obj_id
                temp = self._get_state(state_id)
                if temp and temp not in ['null', 'undefined']:
                    try:
                        temp_val = float(temp)
                        return f"Die Temperatur bei '{match['name']}' beträgt {temp_val:.1f}°C."
                    except ValueError:
                        continue
        
        return f"Konnte Temperatur von '{device_name}' nicht lesen."
    
    def set_blinds(self, device_name: str, position: int) -> str:
        """
        Set position of blinds/shutters.
        
        Args:
            device_name: Name of the blinds
            position: Position 0 (closed) to 100 (open)
            
        Returns:
            Status message
        """
        logger.info(f"Setze Rollo '{device_name}' auf {position}%...")
        
        position = max(0, min(100, position))
        
        # Find blind device
        device = self._find_device(device_name, device_type='blind')
        if not device:
            # Try without type filter
            device = self._find_device(device_name)
        
        if not device:
            return f"Rollo '{device_name}' nicht gefunden."
        
        # Use Blind-Lift-rangeValue for Alexa blinds
        if device.get('blind_state'):
            if self._set_state(device['blind_state'], position):
                status = "geschlossen" if position == 0 else "geöffnet" if position == 100 else f"auf {position}%"
                return f"Rollo '{device['name']}' {status}."
        
        return f"Konnte Rollo '{device_name}' nicht steuern."
    
    def list_devices(self) -> str:
        """
        List all available smart home devices.
        
        Returns:
            List of device names by type
        """
        logger.info("Liste alle Smart Home Geräte auf...")
        
        if not self._devices:
            return "Keine Smart Home Geräte gefunden."
        
        # Group by type
        blinds = [d['name'] for d in self._devices.values() if d['type'] == 'blind']
        lights = [d['name'] for d in self._devices.values() if d['type'] in ['switch', 'dimmer']]
        
        result_parts = []
        if blinds:
            result_parts.append(f"Rolladen: {', '.join(blinds[:10])}")
        if lights:
            result_parts.append(f"Lichter/Schalter: {', '.join(lights[:10])}")
        
        return ". ".join(result_parts) if result_parts else "Keine steuerbaren Geräte gefunden."
    
    def execute_scene(self, scene_name: str) -> str:
        """
        Execute a scene/script in ioBroker.
        
        Args:
            scene_name: Name of the scene to execute
            
        Returns:
            Status message
        """
        logger.info(f"Führe Szene '{scene_name}' aus...")
        
        # Try to find scene in common adapters
        scene_prefixes = ['scene.0.', 'scenes.0.', 'javascript.0.']
        
        for prefix in scene_prefixes:
            scene_id = f"{prefix}{scene_name}"
            if self._set_state(scene_id, True):
                return f"Szene '{scene_name}' wurde ausgeführt."
        
        # Try to find by name
        matches = self._find_device(scene_name)
        for match in matches:
            if 'scene' in match['id'].lower() or 'script' in match['id'].lower():
                if self._set_state(match['id'], True):
                    return f"Szene '{match['name']}' wurde ausgeführt."
        
        return f"Szene '{scene_name}' nicht gefunden."
    
    def get_tool_definitions(self) -> list[dict]:
        """Return tool definitions for Gemini."""
        return [
            {
                "name": "turn_on_device",
                "description": "Schaltet ein Smart Home Gerät ein (Licht, Steckdose, Schalter). Beispiel: 'Schalte das Wohnzimmerlicht ein'",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "device_name": {
                            "type": "string",
                            "description": "Name des Geräts, z.B. 'Wohnzimmer Licht', 'Stehlampe', 'Kaffeemaschine'"
                        }
                    },
                    "required": ["device_name"]
                }
            },
            {
                "name": "turn_off_device",
                "description": "Schaltet ein Smart Home Gerät aus. Beispiel: 'Schalte die Stehlampe aus'",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "device_name": {
                            "type": "string",
                            "description": "Name des Geräts"
                        }
                    },
                    "required": ["device_name"]
                }
            },
            {
                "name": "set_brightness",
                "description": "Stellt die Helligkeit einer dimmbaren Lampe ein. Beispiel: 'Dimme das Licht auf 50%'",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "device_name": {
                            "type": "string",
                            "description": "Name der Lampe"
                        },
                        "brightness": {
                            "type": "integer",
                            "description": "Helligkeit in Prozent (0-100)"
                        }
                    },
                    "required": ["device_name", "brightness"]
                }
            },
            {
                "name": "set_color",
                "description": "Ändert die Farbe einer RGB-Lampe. Beispiel: 'Mach das Licht rot'",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "device_name": {
                            "type": "string",
                            "description": "Name der Lampe"
                        },
                        "color": {
                            "type": "string",
                            "description": "Farbe als Name (rot, grün, blau, gelb, weiß, warmweiß, etc.) oder Hex-Code"
                        }
                    },
                    "required": ["device_name", "color"]
                }
            },
            {
                "name": "set_temperature",
                "description": "Stellt die Zieltemperatur eines Thermostats ein. Beispiel: 'Stelle die Heizung im Wohnzimmer auf 21 Grad'",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "device_name": {
                            "type": "string",
                            "description": "Name des Thermostats oder Raums"
                        },
                        "temperature": {
                            "type": "number",
                            "description": "Zieltemperatur in Celsius (5-30)"
                        }
                    },
                    "required": ["device_name", "temperature"]
                }
            },
            {
                "name": "get_temperature",
                "description": "Liest die aktuelle Temperatur eines Sensors. Beispiel: 'Wie warm ist es im Schlafzimmer?'",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "device_name": {
                            "type": "string",
                            "description": "Name des Sensors oder Raums"
                        }
                    },
                    "required": ["device_name"]
                }
            },
            {
                "name": "set_blinds",
                "description": "Steuert Rollos oder Jalousien. 0=geschlossen, 100=offen. Beispiel: 'Öffne die Rollos im Wohnzimmer'",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "device_name": {
                            "type": "string",
                            "description": "Name des Rollos"
                        },
                        "position": {
                            "type": "integer",
                            "description": "Position in Prozent (0=zu, 100=auf)"
                        }
                    },
                    "required": ["device_name", "position"]
                }
            },
            {
                "name": "list_devices",
                "description": "Listet alle verfügbaren Smart Home Geräte auf. Beispiel: 'Welche Geräte habe ich?'",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "execute_scene",
                "description": "Führt eine Szene oder ein Skript aus. Beispiel: 'Starte die Filmszene'",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "scene_name": {
                            "type": "string",
                            "description": "Name der Szene"
                        }
                    },
                    "required": ["scene_name"]
                }
            }
        ]
    
    def get_tool_handlers(self) -> dict[str, Callable]:
        """Return mapping of tool names to handler functions."""
        return {
            "turn_on_device": self.turn_on_device,
            "turn_off_device": self.turn_off_device,
            "set_brightness": self.set_brightness,
            "set_color": self.set_color,
            "set_temperature": self.set_temperature,
            "get_temperature": self.get_temperature,
            "set_blinds": self.set_blinds,
            "list_devices": self.list_devices,
            "execute_scene": self.execute_scene,
        }
