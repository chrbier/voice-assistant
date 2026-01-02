"""
Configuration module for Voice Assistant.
Loads settings from environment variables with sensible defaults.
"""

import os
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import Field
from dotenv import load_dotenv

# Load .env file
load_dotenv()


class AudioConfig(BaseSettings):
    """Audio device configuration."""
    input_device: str = Field(default="default", alias="AUDIO_INPUT_DEVICE")
    output_device: str = Field(default="default", alias="AUDIO_OUTPUT_DEVICE")
    sample_rate: int = 16000  # Required for Porcupine and Gemini
    channels: int = 1  # Mono audio
    chunk_size: int = 512  # Porcupine frame length


class PorcupineConfig(BaseSettings):
    """Porcupine wakeword configuration."""
    access_key: str = Field(alias="PORCUPINE_ACCESS_KEY")
    keyword: str = "computer"  # Built-in keyword
    sensitivity: float = Field(default=0.7, alias="PORCUPINE_SENSITIVITY")  # 0.0 to 1.0, higher = more sensitive


class GeminiConfig(BaseSettings):
    """Gemini Live API configuration."""
    api_key: str = Field(alias="GEMINI_API_KEY")
    # Native audio model for Live API
    model: str = "gemini-2.5-flash-native-audio-preview-12-2025"
    
    # Audio format settings (required by Gemini)
    input_sample_rate: int = 16000
    output_sample_rate: int = 24000


class GoogleCalendarConfig(BaseSettings):
    """Google Calendar API configuration."""
    enabled: bool = Field(default=True, alias="GOOGLE_CALENDAR_ENABLED")
    credentials_file: str = Field(default="credentials.json", alias="GOOGLE_CREDENTIALS_FILE")
    token_file: str = "token.json"
    scopes: list[str] = [
        "https://www.googleapis.com/auth/calendar",
        "https://www.googleapis.com/auth/calendar.events"
    ]


class SmartHomeConfig(BaseSettings):
    """ioBroker Smart Home configuration."""
    iobroker_host: str = Field(default="192.168.178.100", alias="IOBROKER_HOST")
    iobroker_port: int = Field(default=8087, alias="IOBROKER_PORT")
    enabled: bool = Field(default=True, alias="SMARTHOME_ENABLED")


class AssistantConfig(BaseSettings):
    """General assistant configuration."""
    name: str = Field(default="Computer", alias="ASSISTANT_NAME")
    language: str = Field(default="de-DE", alias="LANGUAGE")
    conversation_timeout: int = Field(default=30, alias="CONVERSATION_TIMEOUT_SECONDS")
    
    # Sound files
    sounds_dir: Path = Path(__file__).parent.parent / "sounds"
    activation_sound: str = "activation.wav"
    deactivation_sound: str = "deactivation.wav"
    
    # System prompt for Gemini
    system_prompt: str = """Du bist ein hilfreicher Sprachassistent namens Computer. 
Du antwortest auf Deutsch in natürlicher, gesprochener Sprache.
Halte deine Antworten kurz und prägnant, da sie vorgelesen werden.

Du hast Zugriff auf folgende Funktionen:
- Google Kalender: Termine erstellen, anzeigen, bearbeiten und löschen
- Smart Home: Lichter, Steckdosen, Dimmer, Rollos und Thermostate steuern
- Musik: Musik von YouTube abspielen und stoppen
- Timer: Countdown-Timer mit Alarm setzen, pausieren, stoppen
- Wetter: Aktuelles Wetter und Vorhersage abrufen
- Nachrichten: Aktuelle Schlagzeilen von Tagesschau, Spiegel, etc.
- Web-Recherche: Im Internet nach aktuellen Informationen suchen

Wenn der Benutzer nach Terminen, Wetter, Nachrichten fragt, Smart Home steuern, Musik hören, Timer stellen oder etwas recherchieren will, nutze die verfügbaren Tools.
Beispiele: 'Wie wird das Wetter morgen?', 'Suche nach Tesla Aktie', 'Wer hat gestern gewonnen?'

WICHTIG zur Spracherkennung: Wenn du bei einem gesprochenen Begriff unsicher bist oder er ungewöhnlich/unlogisch klingt, frage kurz nach bevor du handelst. Beispiel: "Meintest du Flurlicht oder Fluorlicht?" - Lieber einmal nachfragen als falsch handeln.

WICHTIG: Wenn der Benutzer die Konversation beenden möchte (z.B. 'Danke', 'Tschüss', 'Das war alles', 'Fertig', 'Auf Wiedersehen'), rufe SOFORT das end_conversation Tool auf ohne dich zu verabschieden - ein Bestätigungston wird automatisch abgespielt.
Sei freundlich und hilfsbereit."""


class Config:
    """Main configuration class combining all settings."""
    
    def __init__(self):
        self.audio = AudioConfig()
        self.porcupine = PorcupineConfig()
        self.gemini = GeminiConfig()
        self.calendar = GoogleCalendarConfig()
        self.smarthome = SmartHomeConfig()
        self.assistant = AssistantConfig()
    
    def validate(self) -> list[str]:
        """Validate configuration and return list of errors."""
        errors = []
        
        if not self.porcupine.access_key or self.porcupine.access_key == "your_porcupine_access_key_here":
            errors.append("PORCUPINE_ACCESS_KEY nicht gesetzt")
        
        if not self.gemini.api_key or self.gemini.api_key == "your_gemini_api_key_here":
            errors.append("GEMINI_API_KEY nicht gesetzt")
        
        # Calendar credentials are optional - just log warning
        # if not Path(self.calendar.credentials_file).exists():
        #     errors.append(f"Google Credentials Datei nicht gefunden: {self.calendar.credentials_file}")
        
        return errors
    
    def has_calendar_credentials(self) -> bool:
        """Check if Google Calendar credentials are available."""
        return Path(self.calendar.credentials_file).exists()


# Global config instance
config = Config()
