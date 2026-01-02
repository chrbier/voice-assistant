"""
Main Voice Assistant orchestrator.
Coordinates wakeword detection, audio streaming, and Gemini communication.
"""

import asyncio
import logging
import signal
from typing import Optional
from datetime import datetime, timedelta
import numpy as np

try:
    import sounddevice as sd
    _use_sounddevice = True
except OSError:
    import pyaudio
    _use_sounddevice = False

from src.config import config
from src.audio.handler import AudioHandler
from src.audio.player import AudioPlayer
from src.wakeword.detector import WakewordDetector
from src.gemini.client import GeminiLiveClient
from src.tools.calendar import GoogleCalendarTool
from src.tools.smarthome import SmartHomeTool
from src.tools.music import MusicTool
from src.tools.timer import TimerTool
from src.tools.weather import WeatherTool
from src.tools.news import NewsTool
from src.tools.websearch import WebSearchTool
from src.tools.memory import MemoryTool

logger = logging.getLogger(__name__)


class VoiceAssistant:
    """
    Main voice assistant class.
    Manages the lifecycle of wakeword detection, conversation, and tool execution.
    """
    
    def __init__(self):
        self._audio_handler = AudioHandler()
        self._audio_player = AudioPlayer()
        self._wakeword_detector: Optional[WakewordDetector] = None
        self._gemini_client: Optional[GeminiLiveClient] = None
        self._calendar_tool: Optional[GoogleCalendarTool] = None
        self._smarthome_tool: Optional[SmartHomeTool] = None
        self._music_tool: Optional[MusicTool] = None
        self._timer_tool: Optional[TimerTool] = None
        self._weather_tool: Optional[WeatherTool] = None
        self._news_tool: Optional[NewsTool] = None
        self._websearch_tool: Optional[WebSearchTool] = None
        self._memory_tool: Optional[MemoryTool] = None
        
        self._is_running = False
        self._is_in_conversation = False
        self._conversation_start_time: Optional[datetime] = None
        self._last_activity_time: Optional[datetime] = None
        self._end_conversation_requested = False  # For early conversation ending
        
        # Conversation timeout check interval
        self._timeout_check_interval = 1.0  # seconds
    
    async def initialize(self) -> None:
        """Initialize all components."""
        logger.info("Initialisiere Voice Assistant...")
        
        # Validate configuration
        errors = config.validate()
        if errors:
            for error in errors:
                logger.error(f"Konfigurationsfehler: {error}")
            raise RuntimeError("Konfiguration ungültig - bitte .env Datei prüfen")
        
        # Initialize wakeword detector
        self._wakeword_detector = WakewordDetector()
        self._wakeword_detector.initialize()
        
        # Initialize Gemini client
        self._gemini_client = GeminiLiveClient()
        
        # Initialize calendar tool (optional)
        if config.has_calendar_credentials():
            self._calendar_tool = GoogleCalendarTool()
            try:
                self._calendar_tool.initialize()
                logger.info("✓ Google Calendar verbunden")
            except Exception as e:
                logger.warning(f"Google Calendar nicht verfügbar: {e}")
                self._calendar_tool = None
        else:
            logger.info("ℹ️  Starte ohne Google Calendar (credentials.json nicht gefunden)")
        
        # Initialize Smart Home tool (optional)
        if config.smarthome.enabled:
            self._smarthome_tool = SmartHomeTool()
            try:
                self._smarthome_tool.initialize()
                logger.info("✓ Smart Home (ioBroker) verbunden")
            except Exception as e:
                logger.warning(f"Smart Home nicht verfügbar: {e}")
                self._smarthome_tool = None
        
        # Initialize Music tool (optional)
        self._music_tool = MusicTool()
        try:
            self._music_tool.initialize()
            logger.info("✓ Musik-Player verfügbar")
        except Exception as e:
            logger.warning(f"Musik-Player nicht verfügbar: {e}")
            self._music_tool = None
        
        # Initialize Timer tool
        self._timer_tool = TimerTool(audio_player=self._audio_player)
        try:
            self._timer_tool.initialize()
            logger.info("✓ Timer verfügbar")
        except Exception as e:
            logger.warning(f"Timer nicht verfügbar: {e}")
            self._timer_tool = None
        
        # Initialize Weather tool (optional - requires API key)
        self._weather_tool = WeatherTool()
        try:
            self._weather_tool.initialize()
            logger.info("✓ Wetter verfügbar")
        except Exception as e:
            logger.warning(f"Wetter nicht verfügbar: {e}")
            self._weather_tool = None
        
        # Initialize News tool
        self._news_tool = NewsTool()
        try:
            self._news_tool.initialize()
            logger.info("✓ Nachrichten verfügbar")
        except Exception as e:
            logger.warning(f"Nachrichten nicht verfügbar: {e}")
            self._news_tool = None
        
        # Initialize Web Search tool (optional - requires API key)
        self._websearch_tool = WebSearchTool()
        try:
            self._websearch_tool.initialize()
            logger.info("✓ Web-Recherche verfügbar")
        except Exception as e:
            logger.warning(f"Web-Recherche nicht verfügbar: {e}")
            self._websearch_tool = None
        
        # Initialize Memory tool (ChromaDB)
        self._memory_tool = MemoryTool()
        try:
            self._memory_tool.initialize()
            logger.info("✓ Gedächtnis verfügbar")
        except Exception as e:
            logger.warning(f"Gedächtnis nicht verfügbar: {e}")
            self._memory_tool = None
        
        # Register all available tools
        self._register_tools()
        
        # Set up Gemini callbacks
        self._gemini_client.set_callbacks(
            on_audio=self._on_gemini_audio,
            on_text=self._on_gemini_text,
            on_turn_complete=self._on_turn_complete
        )
        
        logger.info("Voice Assistant initialisiert")
    
    def _register_tools(self) -> None:
        """Register all tools with Gemini client."""
        tools_registered = 0
        
        # Register Calendar tools
        if self._calendar_tool:
            for tool_def in self._calendar_tool.get_tool_definitions():
                handler = self._calendar_tool.get_tool_handlers().get(tool_def["name"])
                if handler:
                    self._gemini_client.register_tool(
                        name=tool_def["name"],
                        description=tool_def["description"],
                        parameters=tool_def["parameters"],
                        handler=handler
                    )
                    tools_registered += 1
        
        # Register Smart Home tools
        if self._smarthome_tool:
            for tool_def in self._smarthome_tool.get_tool_definitions():
                handler = self._smarthome_tool.get_tool_handlers().get(tool_def["name"])
                if handler:
                    self._gemini_client.register_tool(
                        name=tool_def["name"],
                        description=tool_def["description"],
                        parameters=tool_def["parameters"],
                        handler=handler
                    )
                    tools_registered += 1
        
        # Register Music tools
        if self._music_tool:
            for tool_def in self._music_tool.get_tool_definitions():
                handler = self._music_tool.get_tool_handlers().get(tool_def["name"])
                if handler:
                    self._gemini_client.register_tool(
                        name=tool_def["name"],
                        description=tool_def["description"],
                        parameters=tool_def["parameters"],
                        handler=handler
                    )
                    tools_registered += 1
        
        # Register Timer tools
        if self._timer_tool:
            for tool_def in self._timer_tool.get_tool_definitions():
                handler = self._timer_tool.get_tool_handlers().get(tool_def["name"])
                if handler:
                    self._gemini_client.register_tool(
                        name=tool_def["name"],
                        description=tool_def["description"],
                        parameters=tool_def["parameters"],
                        handler=handler
                    )
                    tools_registered += 1
        
        # Register Weather tools
        if self._weather_tool:
            for tool_def in self._weather_tool.get_tool_definitions():
                handler = self._weather_tool.get_tool_handlers().get(tool_def["name"])
                if handler:
                    self._gemini_client.register_tool(
                        name=tool_def["name"],
                        description=tool_def["description"],
                        parameters=tool_def["parameters"],
                        handler=handler
                    )
                    tools_registered += 1
        
        # Register News tools
        if self._news_tool:
            for tool_def in self._news_tool.get_tool_definitions():
                handler = self._news_tool.get_tool_handlers().get(tool_def["name"])
                if handler:
                    self._gemini_client.register_tool(
                        name=tool_def["name"],
                        description=tool_def["description"],
                        parameters=tool_def["parameters"],
                        handler=handler
                    )
                    tools_registered += 1
        
        # Register Web Search tools
        if self._websearch_tool:
            for tool_def in self._websearch_tool.get_tool_definitions():
                handler = self._websearch_tool.get_tool_handlers().get(tool_def["name"])
                if handler:
                    self._gemini_client.register_tool(
                        name=tool_def["name"],
                        description=tool_def["description"],
                        parameters=tool_def["parameters"],
                        handler=handler
                    )
                    tools_registered += 1
        
        # Register Memory tools
        if self._memory_tool:
            for tool_def in self._memory_tool.get_tool_definitions():
                handler = self._memory_tool.get_tool_handlers().get(tool_def["name"])
                if handler:
                    self._gemini_client.register_tool(
                        name=tool_def["name"],
                        description=tool_def["description"],
                        parameters=tool_def["parameters"],
                        handler=handler
                    )
                    tools_registered += 1
        
        # Register conversation control tool (always available)
        self._gemini_client.register_tool(
            name="end_conversation",
            description="Beendet die aktuelle Konversation und wechselt zurück in den Wakeword-Modus. Nutze dies wenn der Benutzer sich verabschiedet, 'Danke' sagt, 'Tschüss', 'Auf Wiedersehen', 'Das war alles', 'Fertig', oder explizit die Konversation beenden möchte.",
            parameters={
                "type": "object",
                "properties": {}
            },
            handler=self._handle_end_conversation
        )
        tools_registered += 1
        
        logger.info(f"✓ {tools_registered} Tools registriert")
    
    def _handle_end_conversation(self) -> str:
        """Handle end conversation request from Gemini."""
        logger.info("🔚 Benutzer möchte Konversation beenden")
        self._end_conversation_requested = True
        return "Konversation wird beendet. Auf Wiedersehen!"
    
    def _on_gemini_audio(self, audio_data: bytes) -> None:
        """Handle audio response from Gemini."""
        # Queue audio for playback using new thread-safe method
        self._audio_player.queue_audio(audio_data)
        
        # Update activity time
        self._last_activity_time = datetime.now()
    
    def _on_gemini_text(self, text: str) -> None:
        """Handle text response from Gemini (for logging)."""
        logger.debug(f"Gemini Text: {text}")
        self._last_activity_time = datetime.now()
    
    def _on_turn_complete(self) -> None:
        """Handle turn completion from Gemini."""
        logger.debug("Gemini Turn abgeschlossen")
        self._last_activity_time = datetime.now()
    
    async def _wakeword_loop(self) -> None:
        """Main loop for wakeword detection."""
        self._wakeword_detector.start()
        
        # Get Porcupine's required frame length and sample rate
        frame_length = self._wakeword_detector.frame_length
        sample_rate = self._wakeword_detector.sample_rate
        
        logger.debug(f"Wakeword-Loop: frame_length={frame_length}, sample_rate={sample_rate}")
        
        # Set up dedicated audio stream for wakeword detection
        if _use_sounddevice:
            stream = sd.InputStream(
                samplerate=sample_rate,
                channels=1,
                dtype=np.int16,
                blocksize=frame_length
            )
            stream.start()
        else:
            p = pyaudio.PyAudio()
            stream = p.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=sample_rate,
                input=True,
                frames_per_buffer=frame_length
            )
        
        try:
            while self._is_running and not self._is_in_conversation:
                try:
                    # Read audio frame with correct size for Porcupine
                    if _use_sounddevice:
                        audio_data, overflowed = stream.read(frame_length)
                        audio_frame = audio_data.flatten()
                    else:
                        data = stream.read(frame_length, exception_on_overflow=False)
                        audio_frame = np.frombuffer(data, dtype=np.int16)
                    
                    # Check for wakeword
                    if self._wakeword_detector.process_frame(audio_frame):
                        await self._start_conversation()
                    
                    # Small yield to allow other async tasks
                    await asyncio.sleep(0.001)
                    
                except Exception as e:
                    logger.error(f"Fehler in Wakeword-Loop: {e}")
                    await asyncio.sleep(0.1)
        finally:
            # Clean up audio stream
            if _use_sounddevice:
                stream.stop()
                stream.close()
            else:
                stream.stop_stream()
                stream.close()
                p.terminate()
    
    async def _start_conversation(self) -> None:
        """Start a conversation session after wakeword detection."""
        logger.info("🎙️ Starte Konversation...")
        
        # Play activation sound
        self._audio_player.play_activation_sound()
        
        self._is_in_conversation = True
        self._conversation_start_time = datetime.now()
        self._last_activity_time = datetime.now()
        
        try:
            # Connect to Gemini
            await self._gemini_client.connect()
            
            # Start audio streaming and playback
            await self._audio_handler.start_streaming()
            await self._audio_player.start_playback_stream()
            
            # Run conversation loop
            await self._conversation_loop()
            
        except Exception as e:
            logger.error(f"Konversationsfehler: {e}")
        finally:
            await self._end_conversation()
    
    async def _conversation_loop(self) -> None:
        """Main conversation loop - streams audio to Gemini and receives responses."""
        
        # Start tasks for sending audio, Gemini session, and timeout
        send_task = asyncio.create_task(self._send_audio_loop())
        session_task = asyncio.create_task(self._gemini_client.run_session())
        timeout_task = asyncio.create_task(self._conversation_timeout_loop())
        
        try:
            # Wait for any task to complete (usually timeout)
            done, pending = await asyncio.wait(
                [send_task, session_task, timeout_task],
                return_when=asyncio.FIRST_COMPLETED
            )
            
            # Cancel remaining tasks
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                    
        except Exception as e:
            logger.error(f"Conversation loop Fehler: {e}")
    
    async def _send_audio_loop(self) -> None:
        """Send audio to Gemini."""
        try:
            async for audio_chunk in self._audio_handler.get_audio_stream():
                if not self._is_in_conversation:
                    break
                
                await self._gemini_client.send_audio(audio_chunk)
                
        except Exception as e:
            logger.error(f"Audio-Senden Fehler: {e}")
    
    async def _receive_response_loop(self) -> None:
        """Legacy - responses now handled by Gemini client internally."""
        # Keep running while in conversation
        while self._is_in_conversation:
            await asyncio.sleep(0.1)
    
    async def _conversation_timeout_loop(self) -> None:
        """Monitor conversation timeout and early end requests."""
        timeout = config.assistant.conversation_timeout
        
        while self._is_in_conversation:
            await asyncio.sleep(self._timeout_check_interval)
            
            # Check for early end request
            if self._end_conversation_requested:
                logger.info("👋 Konversation wird auf Anfrage beendet")
                self._is_in_conversation = False
                self._end_conversation_requested = False
                break
            
            if self._last_activity_time:
                elapsed = (datetime.now() - self._last_activity_time).total_seconds()
                
                if elapsed > timeout:
                    logger.info(f"⏱️ Konversations-Timeout nach {timeout}s Inaktivität")
                    self._is_in_conversation = False
                    break
    
    async def _end_conversation(self) -> None:
        """End the current conversation session."""
        logger.info("🔚 Beende Konversation...")
        
        self._is_in_conversation = False
        
        # Stop streaming
        await self._audio_handler.stop_streaming()
        await self._audio_player.stop_playback_stream()
        
        # Disconnect from Gemini
        await self._gemini_client.disconnect()
        
        # Play deactivation sound
        self._audio_player.play_deactivation_sound()
        
        logger.info("Zurück im Wakeword-Modus")
    
    async def run(self) -> None:
        """Main run loop."""
        self._is_running = True
        
        logger.info("=" * 50)
        logger.info(f"🤖 {config.assistant.name} gestartet")
        logger.info(f"   Wakeword: '{config.porcupine.keyword}'")
        logger.info(f"   Timeout: {config.assistant.conversation_timeout}s")
        logger.info("=" * 50)
        logger.info("Sage 'Computer' um eine Konversation zu starten...")
        
        try:
            while self._is_running:
                # Run wakeword detection until triggered
                await self._wakeword_loop()
                
                # Small delay before returning to wakeword mode
                if self._is_running:
                    await asyncio.sleep(0.5)
                    
        except asyncio.CancelledError:
            logger.info("Assistant wurde abgebrochen")
        except Exception as e:
            logger.error(f"Unerwarteter Fehler: {e}")
            raise
    
    async def stop(self) -> None:
        """Stop the assistant gracefully."""
        logger.info("Stoppe Voice Assistant...")
        
        self._is_running = False
        self._is_in_conversation = False
        
        # Clean up components
        if self._wakeword_detector:
            self._wakeword_detector.cleanup()
        
        if self._gemini_client and self._gemini_client.is_connected:
            await self._gemini_client.disconnect()
        
        self._audio_handler.cleanup()
        self._audio_player.cleanup()
        
        logger.info("Voice Assistant gestoppt")


async def main():
    """Main entry point."""
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    assistant = VoiceAssistant()
    
    # Set up signal handlers for graceful shutdown
    loop = asyncio.get_running_loop()
    
    def signal_handler():
        logger.info("Signal empfangen, stoppe...")
        asyncio.create_task(assistant.stop())
    
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, signal_handler)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass
    
    try:
        await assistant.initialize()
        await assistant.run()
    except KeyboardInterrupt:
        logger.info("Keyboard Interrupt")
    finally:
        await assistant.stop()


if __name__ == "__main__":
    asyncio.run(main())
