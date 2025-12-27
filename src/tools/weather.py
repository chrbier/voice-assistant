"""
Weather Tool using OpenWeatherMap API.
Provides current weather and forecasts.
"""

import logging
import os
import urllib.request
import urllib.parse
import json
from typing import Optional, Callable, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class WeatherTool:
    """
    Weather information using OpenWeatherMap API.
    Supports current weather and 5-day forecast.
    """
    
    def __init__(self):
        self._api_key = os.getenv("OPENWEATHERMAP_API_KEY", "")
        self._base_url = "https://api.openweathermap.org/data/2.5"
        self._default_city = os.getenv("WEATHER_DEFAULT_CITY", "Berlin")
        self._units = "metric"  # Celsius
        self._lang = "de"
    
    def initialize(self) -> None:
        """Check if API key is configured."""
        if not self._api_key:
            raise RuntimeError(
                "OPENWEATHERMAP_API_KEY nicht gesetzt. "
                "Hole einen kostenlosen Key von https://openweathermap.org/api"
            )
        # Log masked key for debugging
        masked_key = self._api_key[:4] + "..." + self._api_key[-4:] if len(self._api_key) > 8 else "***"
        logger.info(f"✓ Wetter-Tool initialisiert (Key: {masked_key}, Stadt: {self._default_city})")
    
    def _make_request(self, endpoint: str, params: Dict[str, str]) -> Optional[Dict[str, Any]]:
        """Make HTTP request to OpenWeatherMap API."""
        params["appid"] = self._api_key
        params["units"] = self._units
        params["lang"] = self._lang
        
        query_string = urllib.parse.urlencode(params)
        url = f"{self._base_url}/{endpoint}?{query_string}"
        
        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                data = json.loads(response.read().decode())
                return data
        except urllib.error.HTTPError as e:
            if e.code == 404:
                logger.warning(f"Stadt nicht gefunden")
            else:
                logger.error(f"API-Fehler: {e.code}")
            return None
        except Exception as e:
            logger.error(f"Wetter-Anfrage fehlgeschlagen: {e}")
            return None
    
    def _format_weather(self, data: Dict[str, Any]) -> str:
        """Format weather data to human-readable string."""
        try:
            city = data.get("name", "Unbekannt")
            weather = data.get("weather", [{}])[0]
            main = data.get("main", {})
            wind = data.get("wind", {})
            
            description = weather.get("description", "unbekannt").capitalize()
            temp = main.get("temp", 0)
            feels_like = main.get("feels_like", 0)
            humidity = main.get("humidity", 0)
            wind_speed = wind.get("speed", 0)
            
            result = f"In {city}: {description}, {temp:.1f}°C"
            
            if abs(feels_like - temp) > 2:
                result += f" (gefühlt {feels_like:.1f}°C)"
            
            result += f". Luftfeuchtigkeit {humidity}%"
            
            if wind_speed > 0:
                result += f", Wind {wind_speed:.1f} m/s"
            
            return result
            
        except Exception as e:
            logger.error(f"Fehler beim Formatieren: {e}")
            return "Wetterdaten konnten nicht formatiert werden."
    
    def _format_forecast(self, data: Dict[str, Any], days: int = 3) -> str:
        """Format forecast data to human-readable string."""
        try:
            city = data.get("city", {}).get("name", "Unbekannt")
            forecast_list = data.get("list", [])
            
            if not forecast_list:
                return "Keine Vorhersagedaten verfügbar."
            
            # Group by day (noon forecasts)
            daily_forecasts = {}
            for item in forecast_list:
                dt = datetime.fromtimestamp(item["dt"])
                date_str = dt.strftime("%Y-%m-%d")
                hour = dt.hour
                
                # Prefer noon (12:00) or closest to it
                if date_str not in daily_forecasts or abs(hour - 12) < abs(daily_forecasts[date_str]["hour"] - 12):
                    daily_forecasts[date_str] = {
                        "hour": hour,
                        "data": item,
                        "date": dt
                    }
            
            # Sort and take requested days
            sorted_dates = sorted(daily_forecasts.keys())
            
            # Skip today if it's late
            if sorted_dates and datetime.now().hour > 18:
                sorted_dates = sorted_dates[1:]
            
            forecasts = []
            day_names = ["Heute", "Morgen", "Übermorgen"]
            
            for i, date_str in enumerate(sorted_dates[:days]):
                forecast = daily_forecasts[date_str]
                item = forecast["data"]
                
                weather = item.get("weather", [{}])[0]
                main = item.get("main", {})
                
                description = weather.get("description", "unbekannt")
                temp = main.get("temp", 0)
                
                day_name = day_names[i] if i < len(day_names) else forecast["date"].strftime("%A")
                forecasts.append(f"{day_name}: {description}, {temp:.0f}°C")
            
            return f"Wettervorhersage für {city}: " + ". ".join(forecasts)
            
        except Exception as e:
            logger.error(f"Fehler bei Vorhersage-Formatierung: {e}")
            return "Vorhersage konnte nicht formatiert werden."
    
    # === Tool Functions for Gemini ===
    
    def get_current_weather(self, city: str = "") -> str:
        """
        Get current weather for a city.
        
        Args:
            city: City name (default: configured default city)
            
        Returns:
            Weather description
        """
        city = city.strip() if city else self._default_city
        logger.info(f"🌤 Wetter-Abfrage: {city}")
        
        data = self._make_request("weather", {"q": city})
        
        if not data:
            return f"Konnte das Wetter für '{city}' nicht abrufen. Ist der Stadtname korrekt?"
        
        return self._format_weather(data)
    
    def get_forecast(self, city: str = "", days: int = 3) -> str:
        """
        Get weather forecast for upcoming days.
        
        Args:
            city: City name (default: configured default city)
            days: Number of days (1-5)
            
        Returns:
            Forecast description
        """
        city = city.strip() if city else self._default_city
        days = max(1, min(5, days))
        logger.info(f"🌤 Vorhersage-Abfrage: {city} ({days} Tage)")
        
        data = self._make_request("forecast", {"q": city})
        
        if not data:
            return f"Konnte die Vorhersage für '{city}' nicht abrufen."
        
        return self._format_forecast(data, days)
    
    def get_tool_definitions(self) -> list[dict]:
        """Return tool definitions for Gemini."""
        return [
            {
                "name": "get_weather",
                "description": f"Ruft das aktuelle Wetter ab. Ohne Stadtangabe wird {self._default_city} verwendet. Beispiel: 'Wie ist das Wetter?' oder 'Wetter in München'",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {
                            "type": "string",
                            "description": "Stadt für die Wetterabfrage (optional)"
                        }
                    }
                }
            },
            {
                "name": "get_weather_forecast",
                "description": f"Ruft die Wettervorhersage für die nächsten Tage ab. Beispiel: 'Wie wird das Wetter morgen?' oder 'Wettervorhersage für Hamburg'",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {
                            "type": "string",
                            "description": "Stadt für die Vorhersage (optional)"
                        },
                        "days": {
                            "type": "integer",
                            "description": "Anzahl der Tage (1-5, Standard: 3)"
                        }
                    }
                }
            }
        ]
    
    def get_tool_handlers(self) -> dict[str, Callable]:
        """Return mapping of tool names to handler functions."""
        return {
            "get_weather": self.get_current_weather,
            "get_weather_forecast": self.get_forecast,
        }
    
    def cleanup(self) -> None:
        """Clean up resources."""
        pass
