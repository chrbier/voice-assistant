"""
Gemini Live API Client for real-time audio streaming.
Uses WebSocket for bidirectional audio communication with native audio support.
"""

import asyncio
import base64
import json
import logging
from typing import AsyncGenerator, Callable, Optional, Any
import websockets
from websockets.client import WebSocketClientProtocol

from src.config import config

logger = logging.getLogger(__name__)


class GeminiLiveClient:
    """
    Client for Gemini Live API with native audio support.
    Handles bidirectional audio streaming and tool calls.
    """
    
    def __init__(self):
        self._ws: Optional[WebSocketClientProtocol] = None
        self._is_connected = False
        self._is_streaming = False
        self._tools: list[dict] = []
        self._tool_handlers: dict[str, Callable] = {}
        self._on_audio_response: Optional[Callable[[bytes], None]] = None
        self._on_text_response: Optional[Callable[[str], None]] = None
        self._on_turn_complete: Optional[Callable[[], None]] = None
        
    def register_tool(self, name: str, description: str, parameters: dict, handler: Callable) -> None:
        """
        Register a tool for function calling.
        
        Args:
            name: Tool name
            description: Tool description
            parameters: JSON schema for parameters
            handler: Async function to handle tool calls
        """
        self._tools.append({
            "name": name,
            "description": description,
            "parameters": parameters
        })
        self._tool_handlers[name] = handler
        logger.info(f"Tool registriert: {name}")
    
    def set_callbacks(
        self,
        on_audio: Optional[Callable[[bytes], None]] = None,
        on_text: Optional[Callable[[str], None]] = None,
        on_turn_complete: Optional[Callable[[], None]] = None
    ) -> None:
        """Set callback functions for responses."""
        self._on_audio_response = on_audio
        self._on_text_response = on_text
        self._on_turn_complete = on_turn_complete
    
    async def connect(self) -> None:
        """Establish WebSocket connection to Gemini Live API."""
        if self._is_connected:
            logger.warning("Bereits verbunden")
            return
        
        # Build WebSocket URL with API key
        ws_url = f"{config.gemini.ws_url}?key={config.gemini.api_key}"
        
        try:
            self._ws = await websockets.connect(
                ws_url,
                extra_headers={
                    "Content-Type": "application/json"
                },
                ping_interval=30,
                ping_timeout=10
            )
            self._is_connected = True
            logger.info("Mit Gemini Live API verbunden")
            
            # Send setup message
            await self._send_setup()
            
        except Exception as e:
            logger.error(f"Verbindungsfehler: {e}")
            raise
    
    async def _send_setup(self) -> None:
        """Send initial setup message with configuration."""
        setup_message = {
            "setup": {
                "model": f"models/{config.gemini.model}",
                "generation_config": {
                    "response_modalities": ["AUDIO"],
                    "speech_config": {
                        "voice_config": {
                            "prebuilt_voice_config": {
                                "voice_name": "Aoede"  # German-compatible voice
                            }
                        }
                    }
                },
                "system_instruction": {
                    "parts": [{"text": config.assistant.system_prompt}]
                },
                "tools": self._build_tools_config()
            }
        }
        
        await self._send_message(setup_message)
        logger.debug("Setup-Nachricht gesendet")
        
        # Wait for setup complete
        response = await self._ws.recv()
        data = json.loads(response)
        
        if "setupComplete" in data:
            logger.info("Gemini Setup abgeschlossen")
        else:
            logger.warning(f"Unerwartete Setup-Antwort: {data}")
    
    def _build_tools_config(self) -> list[dict]:
        """Build tools configuration for Gemini."""
        if not self._tools:
            return []
        
        return [{
            "function_declarations": self._tools
        }]
    
    async def _send_message(self, message: dict) -> None:
        """Send JSON message via WebSocket."""
        if not self._ws:
            raise RuntimeError("Nicht verbunden")
        
        await self._ws.send(json.dumps(message))
    
    async def send_audio(self, audio_data: bytes) -> None:
        """
        Send audio chunk to Gemini.
        Audio should be 16kHz, 16-bit, mono PCM.
        """
        if not self._is_connected:
            return
        
        # Encode audio as base64
        audio_b64 = base64.b64encode(audio_data).decode('utf-8')
        
        message = {
            "realtime_input": {
                "media_chunks": [{
                    "data": audio_b64,
                    "mime_type": "audio/pcm;rate=16000"
                }]
            }
        }
        
        await self._send_message(message)
    
    async def send_text(self, text: str) -> None:
        """Send text message to Gemini."""
        if not self._is_connected:
            return
        
        message = {
            "client_content": {
                "turns": [{
                    "role": "user",
                    "parts": [{"text": text}]
                }],
                "turn_complete": True
            }
        }
        
        await self._send_message(message)
    
    async def end_turn(self) -> None:
        """Signal end of user turn."""
        if not self._is_connected:
            return
        
        message = {
            "client_content": {
                "turn_complete": True
            }
        }
        
        await self._send_message(message)
    
    async def receive_responses(self) -> AsyncGenerator[dict, None]:
        """
        Async generator for receiving responses from Gemini.
        Yields parsed response data.
        """
        if not self._ws:
            return
        
        self._is_streaming = True
        
        try:
            async for message in self._ws:
                try:
                    data = json.loads(message)
                    yield data
                    
                    # Process response
                    await self._process_response(data)
                    
                except json.JSONDecodeError:
                    logger.warning(f"Ungültige JSON-Nachricht: {message[:100]}")
                    
        except websockets.exceptions.ConnectionClosed:
            logger.info("WebSocket-Verbindung geschlossen")
            self._is_connected = False
        except Exception as e:
            logger.error(f"Empfangsfehler: {e}")
        finally:
            self._is_streaming = False
    
    async def _process_response(self, data: dict) -> None:
        """Process a response message from Gemini."""
        
        # Handle server content (audio/text responses)
        if "serverContent" in data:
            content = data["serverContent"]
            
            # Check for model turn
            if "modelTurn" in content:
                model_turn = content["modelTurn"]
                
                for part in model_turn.get("parts", []):
                    # Handle audio response
                    if "inlineData" in part:
                        inline_data = part["inlineData"]
                        if inline_data.get("mimeType", "").startswith("audio/"):
                            audio_bytes = base64.b64decode(inline_data["data"])
                            if self._on_audio_response:
                                self._on_audio_response(audio_bytes)
                    
                    # Handle text response
                    if "text" in part:
                        if self._on_text_response:
                            self._on_text_response(part["text"])
            
            # Check for turn complete
            if content.get("turnComplete"):
                logger.debug("Turn abgeschlossen")
                if self._on_turn_complete:
                    self._on_turn_complete()
        
        # Handle tool calls
        if "toolCall" in data:
            await self._handle_tool_call(data["toolCall"])
    
    async def _handle_tool_call(self, tool_call: dict) -> None:
        """Handle a tool call from Gemini."""
        function_calls = tool_call.get("functionCalls", [])
        
        for fc in function_calls:
            name = fc.get("name")
            args = fc.get("args", {})
            call_id = fc.get("id")
            
            logger.info(f"🔧 Tool-Aufruf: {name}({args})")
            
            if name in self._tool_handlers:
                try:
                    handler = self._tool_handlers[name]
                    
                    # Call handler (async or sync)
                    if asyncio.iscoroutinefunction(handler):
                        result = await handler(**args)
                    else:
                        result = handler(**args)
                    
                    # Send tool response
                    await self._send_tool_response(call_id, name, result)
                    
                except Exception as e:
                    logger.error(f"Tool-Fehler bei {name}: {e}")
                    await self._send_tool_response(call_id, name, {"error": str(e)})
            else:
                logger.warning(f"Unbekanntes Tool: {name}")
                await self._send_tool_response(call_id, name, {"error": f"Tool '{name}' nicht gefunden"})
    
    async def _send_tool_response(self, call_id: str, name: str, result: Any) -> None:
        """Send tool response back to Gemini."""
        # Gemini expects response as a Struct (JSON object), not a plain string
        # Wrap string results in an object
        if isinstance(result, str):
            response_obj = {"result": result}
        elif isinstance(result, dict):
            response_obj = result
        else:
            response_obj = {"result": str(result)}
        
        message = {
            "tool_response": {
                "function_responses": [{
                    "id": call_id,
                    "name": name,
                    "response": response_obj
                }]
            }
        }
        
        await self._send_message(message)
        logger.debug(f"Tool-Antwort gesendet für {name}")
    
    async def disconnect(self) -> None:
        """Close WebSocket connection."""
        self._is_streaming = False
        self._is_connected = False
        
        if self._ws:
            await self._ws.close()
            self._ws = None
            logger.info("Gemini-Verbindung getrennt")
    
    @property
    def is_connected(self) -> bool:
        """Check if connected to Gemini."""
        return self._is_connected
    
    @property
    def is_streaming(self) -> bool:
        """Check if currently streaming."""
        return self._is_streaming
