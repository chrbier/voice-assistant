"""
Smart Home Tool for ioBroker integration.
Controls devices via ioBroker Simple API.
"""

import logging
import requests
from typing import Any, Callable
from src.config import config

logger = logging.getLogger(__name__)


class SmartHomeTool:
    """
    Smart Home control via ioBroker Simple API.
    Supports lights, switches, dimmers, blinds, and thermostats.
    """
    
    def __init__(self):
        self.base_url = f"http://{config.smarthome.iobroker_host}:{config.smarthome.iobroker_port}"
        self._timeout = 5  # seconds
        self._device_cache = {}  # Cache for device states
    
    def initialize(self) -> None:
        """Test connection to ioBroker."""
        try:
            response = requests.get(f"{self.base_url}/getPlainValue/system.adapter.admin.0.alive", timeout=self._timeout)
            if response.status_code == 200:
                logger.info(f"✓ ioBroker verbunden: {self.base_url}")
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
    
    def _find_device(self, device_name: str) -> list[dict]:
        """
        Search for devices by name in ioBroker.
        Returns list of matching object IDs, prioritizing real devices over Alexa routines.
        """
        # Adapters to exclude (system stuff, not devices)
        EXCLUDED_PREFIXES = [
            'alexa2.0.History',
            'alexa2.0.Echo-Devices.*.Routines',  # Exclude routines but not smart home
            'system.',
            'admin.',
        ]
        
        # Patterns to exclude (more specific)
        EXCLUDED_PATTERNS = [
            '.Routines.',     # Alexa routines
            '.Commands.',     # Alexa commands  
            '.History.',      # History entries
        ]
        
        # Preferred adapters for real devices (in priority order)
        PREFERRED_PREFIXES = [
            'alexa2.0.Smart-Home-Devices',  # Alexa Smart Home devices (preferred!)
            'hue.',           # Philips Hue
            'shelly.',        # Shelly devices
            'zigbee.',        # Zigbee devices
            'zigbee2mqtt.',   # Zigbee2MQTT
            'deconz.',        # deCONZ/Phoscon
            'tradfri.',       # IKEA Tradfri
            'mqtt.',          # Generic MQTT
            'sonoff.',        # Sonoff/Tasmota
            'homematic.',     # HomeMatic
            'iot.',           # IoT adapter
            'linkeddevices.', # Linked devices
            'alias.',         # Aliases (user-defined)
            'alexa2.0.',      # Other Alexa devices (fallback)
        ]
        
        try:
            response = requests.get(f"{self.base_url}/objects", timeout=self._timeout)
            if response.status_code != 200:
                return []
            
            objects = response.json()
            matches = []
            device_name_lower = device_name.lower()
            
            for obj_id, obj_data in objects.items():
                # Skip excluded adapters
                if any(obj_id.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
                    continue
                
                # Skip excluded patterns (routines, commands, history)
                if any(pattern in obj_id for pattern in EXCLUDED_PATTERNS):
                    continue
                
                if 'common' in obj_data and 'name' in obj_data['common']:
                    name = obj_data['common']['name']
                    if isinstance(name, dict):
                        name = name.get('de', name.get('en', ''))
                    
                    if device_name_lower in str(name).lower():
                        # Calculate priority (lower = better)
                        priority = 100
                        for i, prefix in enumerate(PREFERRED_PREFIXES):
                            if obj_id.startswith(prefix):
                                priority = i
                                break
                        
                        matches.append({
                            'id': obj_id,
                            'name': name,
                            'type': obj_data.get('type', 'unknown'),
                            'role': obj_data.get('common', {}).get('role', 'unknown'),
                            'priority': priority
                        })
            
            # Sort by priority (preferred adapters first)
            matches.sort(key=lambda x: x['priority'])
            
            return matches
        except Exception as e:
            logger.error(f"Fehler bei Gerätesuche: {e}")
            return []
    
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
        
        matches = self._find_device(device_name)
        if not matches:
            return f"Gerät '{device_name}' nicht gefunden. Bitte prüfe den Namen."
        
        # Find switchable state
        for match in matches:
            obj_id = match['id']
            # Try common patterns for on/off states
            for suffix in ['', '.state', '.STATE', '.on', '.ON', '.switch', '.SWITCH']:
                state_id = obj_id + suffix if suffix else obj_id
                if self._set_state(state_id, True):
                    return f"'{match['name']}' wurde eingeschaltet."
        
        return f"Konnte '{device_name}' nicht einschalten. Gerät gefunden aber nicht schaltbar."
    
    def turn_off_device(self, device_name: str) -> str:
        """
        Turn off a device (light, switch, plug).
        
        Args:
            device_name: Name of the device to turn off
            
        Returns:
            Status message
        """
        logger.info(f"Schalte '{device_name}' aus...")
        
        matches = self._find_device(device_name)
        if not matches:
            return f"Gerät '{device_name}' nicht gefunden. Bitte prüfe den Namen."
        
        for match in matches:
            obj_id = match['id']
            for suffix in ['', '.state', '.STATE', '.on', '.ON', '.switch', '.SWITCH']:
                state_id = obj_id + suffix if suffix else obj_id
                if self._set_state(state_id, False):
                    return f"'{match['name']}' wurde ausgeschaltet."
        
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
        
        matches = self._find_device(device_name)
        if not matches:
            return f"Gerät '{device_name}' nicht gefunden."
        
        for match in matches:
            obj_id = match['id']
            for suffix in ['.brightness', '.BRIGHTNESS', '.level', '.LEVEL', '.dimmer', '.DIMMER']:
                state_id = obj_id + suffix
                if self._set_state(state_id, brightness):
                    return f"Helligkeit von '{match['name']}' auf {brightness}% gesetzt."
        
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
        
        matches = self._find_device(device_name)
        if not matches:
            return f"Rollo '{device_name}' nicht gefunden."
        
        for match in matches:
            obj_id = match['id']
            for suffix in ['.level', '.LEVEL', '.position', '.POSITION', '']:
                state_id = obj_id + suffix if suffix else obj_id
                if self._set_state(state_id, position):
                    status = "geschlossen" if position == 0 else "geöffnet" if position == 100 else f"auf {position}%"
                    return f"Rollo '{match['name']}' {status}."
        
        return f"Konnte Rollo '{device_name}' nicht steuern."
    
    def list_devices(self) -> str:
        """
        List all available smart home devices.
        
        Returns:
            List of device names and types
        """
        logger.info("Liste alle Smart Home Geräte auf...")
        
        # Patterns to exclude
        EXCLUDED_PATTERNS = ['.Routines.', '.Commands.', '.History.', 'system.', 'admin.']
        
        # Patterns that indicate controllable devices
        DEVICE_INDICATORS = [
            'Smart-Home-Devices',  # Alexa Smart Home
            '.on', '.ON',          # On/off states
            '.state', '.STATE',
            '.switch', '.SWITCH',
            '.brightness', '.BRIGHTNESS',
            '.level', '.LEVEL',
        ]
        
        try:
            response = requests.get(f"{self.base_url}/objects", timeout=self._timeout)
            if response.status_code != 200:
                return "Konnte Geräteliste nicht abrufen."
            
            objects = response.json()
            device_names = set()  # Use set to avoid duplicates
            
            for obj_id, obj_data in objects.items():
                # Skip excluded patterns
                if any(pattern in obj_id for pattern in EXCLUDED_PATTERNS):
                    continue
                
                # Check if it's a device-like object
                obj_type = obj_data.get('type', '')
                is_device = obj_type in ['device', 'channel']
                has_indicator = any(ind in obj_id for ind in DEVICE_INDICATORS)
                
                if is_device or has_indicator:
                    if 'common' in obj_data and 'name' in obj_data['common']:
                        name = obj_data['common']['name']
                        if isinstance(name, dict):
                            name = name.get('de', name.get('en', ''))
                        if name and len(name) > 1:
                            device_names.add(str(name))
            
            if device_names:
                # Sort and limit
                sorted_names = sorted(device_names)[:25]
                device_list = ", ".join(sorted_names)
                return f"Verfügbare Geräte: {device_list}"
            else:
                return "Keine Geräte gefunden. Prüfe ob ioBroker Geräte hat."
                
        except Exception as e:
            logger.error(f"Fehler beim Auflisten: {e}")
            return "Fehler beim Abrufen der Geräteliste."
    
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
