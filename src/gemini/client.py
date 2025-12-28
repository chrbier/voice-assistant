"""
Gemini Live API Client using official Google GenAI SDK.
Based on official Google documentation example.
"""

import asyncio
import logging
from typing import Callable, Optional, Any

from google import genai
from google.genai import types

from src.config import config

logger = logging.getLogger(__name__)


class GeminiLiveClient:
    """
    Client for Gemini Live API using official Google GenAI SDK.
    Handles bidirectional audio streaming and tool calls.
    """
    
    def __init__(self):
        self._client = genai.Client(api_key=config.gemini.api_key)
        self._session = None
        self._session_context = None
        self._is_connected = False
        self._tools: list[dict] = []
        self._tool_handlers: dict[str, Callable] = {}
        self._on_audio_response: Optional[Callable[[bytes], None]] = None
        self._on_text_response: Optional[Callable[[str], None]] = None
        self._on_turn_complete: Optional[Callable[[], None]] = None
        
        # Audio queues for the session
        self._audio_input_queue: asyncio.Queue = None
        self._receive_task: asyncio.Task = None
        self._send_task: asyncio.Task = None
        
    def register_tool(self, name: str, description: str, parameters: dict, handler: Callable) -> None:
        """Register a tool for function calling."""
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
    
    def _build_tools_config(self) -> Optional[list]:
        """Build tools configuration for Gemini."""
        if not self._tools:
            return None
        
        function_declarations = []
        for tool in self._tools:
            function_declarations.append(
                types.FunctionDeclaration(
                    name=tool["name"],
                    description=tool["description"],
                    parameters=tool["parameters"]
                )
            )
        
        return [types.Tool(function_declarations=function_declarations)]
    
    def _build_config(self) -> dict:
        """Build configuration for Live API session."""
        cfg = {
            "response_modalities": ["AUDIO"],
            "system_instruction": config.assistant.system_prompt,
        }
        
        tools = self._build_tools_config()
        if tools:
            cfg["tools"] = tools
        
        return cfg
    
    async def connect(self) -> None:
        """Establish connection to Gemini Live API."""
        if self._is_connected:
            logger.warning("Bereits verbunden")
            return
        
        try:
            self._audio_input_queue = asyncio.Queue(maxsize=100)
            
            # Create session context manager
            live_config = self._build_config()
            self._session_context = self._client.aio.live.connect(
                model=config.gemini.model,
                config=live_config
            )
            
            # Enter the context
            self._session = await self._session_context.__aenter__()
            self._is_connected = True
            logger.info("✓ Mit Gemini Live API verbunden (Official SDK)")
            
        except Exception as e:
            logger.error(f"Verbindungsfehler: {e}")
            raise
    
    async def send_audio(self, audio_data: bytes) -> None:
        """Queue audio chunk for sending to Gemini."""
        if not self._is_connected or not self._audio_input_queue:
            return
        
        try:
            # Put in queue, drop if full
            self._audio_input_queue.put_nowait({
                "data": audio_data,
                "mime_type": "audio/pcm"
            })
        except asyncio.QueueFull:
            pass  # Drop frame if queue is full
    
    async def _send_audio_loop(self) -> None:
        """Internal loop to send audio from queue to Gemini."""
        try:
            while self._is_connected and self._session:
                try:
                    msg = await asyncio.wait_for(
                        self._audio_input_queue.get(),
                        timeout=0.1
                    )
                    await self._session.send_realtime_input(audio=msg)
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    if "closed" not in str(e).lower():
                        logger.error(f"Audio-Senden Fehler: {e}")
                    break
        except asyncio.CancelledError:
            pass
    
    async def _receive_audio_loop(self) -> None:
        """Internal loop to receive responses from Gemini."""
        try:
            while self._is_connected and self._session:
                try:
                    turn = self._session.receive()
                    async for response in turn:
                        await self._process_response(response)
                except Exception as e:
                    error_str = str(e).lower()
                    if "closed" in error_str or "cancelled" in error_str:
                        break
                    logger.error(f"Empfangsfehler: {e}")
                    await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            pass
    
    async def run_session(self) -> None:
        """Run the send and receive loops. Call this after connect()."""
        if not self._is_connected:
            return
        
        try:
            async with asyncio.TaskGroup() as tg:
                self._send_task = tg.create_task(self._send_audio_loop())
                self._receive_task = tg.create_task(self._receive_audio_loop())
        except* Exception as eg:
            for e in eg.exceptions:
                if not isinstance(e, asyncio.CancelledError):
                    logger.error(f"Session-Fehler: {e}")
    
    async def _process_response(self, response) -> None:
        """Process a response message from Gemini."""
        
        # Handle server content (audio/text responses)
        if response.server_content:
            content = response.server_content
            
            if content.model_turn:
                for part in content.model_turn.parts:
                    # Handle audio response
                    if part.inline_data and isinstance(part.inline_data.data, bytes):
                        if self._on_audio_response:
                            self._on_audio_response(part.inline_data.data)
                    
                    # Handle text response
                    if part.text:
                        if self._on_text_response:
                            self._on_text_response(part.text)
            
            if content.turn_complete:
                logger.debug("Turn abgeschlossen")
                if self._on_turn_complete:
                    self._on_turn_complete()
        
        # Handle tool calls
        if response.tool_call:
            await self._handle_tool_call(response.tool_call)
    
    async def _handle_tool_call(self, tool_call) -> None:
        """Handle a tool call from Gemini."""
        function_calls = tool_call.function_calls or []
        
        for fc in function_calls:
            name = fc.name
            args = dict(fc.args) if fc.args else {}
            call_id = fc.id
            
            logger.info(f"🔧 Tool-Aufruf: {name}({args})")
            
            if name in self._tool_handlers:
                try:
                    handler = self._tool_handlers[name]
                    
                    if asyncio.iscoroutinefunction(handler):
                        result = await handler(**args)
                    else:
                        result = handler(**args)
                    
                    await self._send_tool_response(call_id, name, result)
                    
                except Exception as e:
                    logger.error(f"Tool-Fehler bei {name}: {e}")
                    await self._send_tool_response(call_id, name, {"error": str(e)})
            else:
                logger.warning(f"Unbekanntes Tool: {name}")
                await self._send_tool_response(call_id, name, {"error": f"Tool '{name}' nicht gefunden"})
    
    async def _send_tool_response(self, call_id: str, name: str, result: Any) -> None:
        """Send tool response back to Gemini."""
        if not self._session:
            return
        
        if isinstance(result, str):
            response_obj = {"result": result}
        elif isinstance(result, dict):
            response_obj = result
        else:
            response_obj = {"result": str(result)}
        
        try:
            await self._session.send_tool_response(
                function_responses=[
                    types.FunctionResponse(
                        id=call_id,
                        name=name,
                        response=response_obj
                    )
                ]
            )
            logger.debug(f"Tool-Antwort gesendet für {name}")
        except Exception as e:
            logger.error(f"Tool-Response Fehler: {e}")
    
    async def disconnect(self) -> None:
        """Close connection to Gemini."""
        self._is_connected = False
        
        # Cancel tasks
        if self._send_task and not self._send_task.done():
            self._send_task.cancel()
        if self._receive_task and not self._receive_task.done():
            self._receive_task.cancel()
        
        # Exit session context
        if self._session_context:
            try:
                await self._session_context.__aexit__(None, None, None)
            except Exception as e:
                logger.debug(f"Disconnect: {e}")
            self._session = None
            self._session_context = None
            logger.info("Gemini-Verbindung getrennt")
    
    # Legacy methods for compatibility with assistant.py
    async def send_text(self, text: str) -> None:
        """Send text message to Gemini."""
        pass
    
    async def end_turn(self) -> None:
        """Signal end of user turn."""
        pass
    
    async def receive_responses(self):
        """Legacy - now handled internally."""
        # Keep running while connected
        while self._is_connected:
            await asyncio.sleep(0.1)
        yield None  # Make it a generator
    
    @property
    def is_connected(self) -> bool:
        return self._is_connected
    
    @property
    def is_streaming(self) -> bool:
        return self._is_connected
