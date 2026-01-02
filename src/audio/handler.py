"""
Audio input handler for capturing microphone audio.
Optimized for Raspberry Pi with USB microphone.
"""

import asyncio
import logging
from typing import AsyncGenerator, Optional, Callable
import numpy as np
from scipy.signal import resample

try:
    import sounddevice as sd
except OSError:
    # Fallback for systems without PortAudio
    sd = None
    import pyaudio

from src.config import config

logger = logging.getLogger(__name__)


class AudioHandler:
    """
    Handles audio input from microphone.
    Provides both synchronous (for wakeword) and async (for streaming) interfaces.
    """
    
    def __init__(self):
        self.target_sample_rate = config.audio.sample_rate  # What Gemini expects (16000 Hz)
        self.channels = config.audio.channels
        self.chunk_size = config.audio.chunk_size
        self._stream = None
        self._is_recording = False
        self._audio_queue: asyncio.Queue = None
        self._use_sounddevice = sd is not None
        self._pyaudio_instance = None
        
        # Don't check sample rate here - defer to start_streaming()
        # This avoids conflicts with wakeword detection
        self.actual_sample_rate = None
        self.actual_chunk_size = None
        self._needs_resampling = False
        self._sample_rate_checked = False
        
        # Mute flag to prevent self-hearing during playback
        self._is_muted = False
    
    def _check_supported_sample_rate(self) -> tuple[int, bool]:
        """Check if target sample rate is supported, return (actual_rate, needs_resampling)."""
        if self._use_sounddevice and sd is not None:
            try:
                sd.check_input_settings(samplerate=self.target_sample_rate)
                return self.target_sample_rate, False
            except Exception:
                # Try common rates that might be supported
                for rate in [48000, 44100]:
                    try:
                        sd.check_input_settings(samplerate=rate)
                        return rate, True
                    except Exception:
                        continue
        return self.target_sample_rate, False
        
    def _get_device_index(self, device_name: str) -> Optional[int]:
        """Get device index by name or return None for default."""
        if device_name == "default":
            return None
            
        if self._use_sounddevice:
            devices = sd.query_devices()
            for i, dev in enumerate(devices):
                if device_name.lower() in dev['name'].lower():
                    return i
        else:
            p = pyaudio.PyAudio()
            for i in range(p.get_device_count()):
                dev = p.get_device_info_by_index(i)
                if device_name.lower() in dev['name'].lower():
                    p.terminate()
                    return i
            p.terminate()
        
        logger.warning(f"Device '{device_name}' nicht gefunden, nutze Standard-Gerät")
        return None
    
    def get_audio_frame_sync(self) -> np.ndarray:
        """
        Get a single audio frame synchronously.
        Used for wakeword detection where we need precise frame sizes.
        Returns: numpy array of int16 audio samples
        """
        if self._use_sounddevice:
            audio_data = sd.rec(
                self.chunk_size,
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype=np.int16,
                device=self._get_device_index(config.audio.input_device)
            )
            sd.wait()
            return audio_data.flatten()
        else:
            if self._pyaudio_instance is None:
                self._pyaudio_instance = pyaudio.PyAudio()
                self._stream = self._pyaudio_instance.open(
                    format=pyaudio.paInt16,
                    channels=self.channels,
                    rate=self.sample_rate,
                    input=True,
                    frames_per_buffer=self.chunk_size,
                    input_device_index=self._get_device_index(config.audio.input_device)
                )
            
            data = self._stream.read(self.chunk_size, exception_on_overflow=False)
            return np.frombuffer(data, dtype=np.int16)
    
    async def start_streaming(self) -> None:
        """Start async audio streaming."""
        # Check sample rate on first use (deferred from __init__ to avoid wakeword conflicts)
        if not self._sample_rate_checked:
            self.actual_sample_rate, self._needs_resampling = self._check_supported_sample_rate()
            if self._needs_resampling:
                self._resample_ratio = self.actual_sample_rate / self.target_sample_rate
                self.actual_chunk_size = int(self.chunk_size * self._resample_ratio)
                logger.info(f"Audio-Handler: Mikrofon bei {self.actual_sample_rate} Hz, Resampling auf {self.target_sample_rate} Hz")
            else:
                self.actual_chunk_size = self.chunk_size
                self.actual_sample_rate = self.target_sample_rate
            self._sample_rate_checked = True
        
        self._audio_queue = asyncio.Queue(maxsize=500)  # Larger queue
        self._is_recording = True
        self._queue_full_count = 0  # Track dropped frames
        
        self._overflow_count = 0
        
        def audio_callback(indata, frames, time, status):
            if status:
                # Only log overflow occasionally to avoid spam
                if 'overflow' in str(status).lower():
                    self._overflow_count += 1
                    if self._overflow_count == 1 or self._overflow_count % 50 == 0:
                        logger.debug(f"Audio input overflow (#{self._overflow_count}) - normal beim Resampling")
                else:
                    logger.warning(f"Audio status: {status}")
            if self._is_recording and self._audio_queue and not self._is_muted:
                try:
                    # Resample if needed
                    if self._needs_resampling:
                        audio_float = indata.flatten().astype(np.float32)
                        resampled = resample(audio_float, self.chunk_size)
                        audio_bytes = resampled.astype(np.int16).tobytes()
                    else:
                        audio_bytes = indata.tobytes()
                    self._audio_queue.put_nowait(audio_bytes)
                except asyncio.QueueFull:
                    # Only log occasionally to avoid spam
                    self._queue_full_count += 1
                    if self._queue_full_count % 100 == 1:
                        logger.debug(f"Audio queue voll, Frames übersprungen: {self._queue_full_count}")
        
        if self._use_sounddevice:
            self._stream = sd.InputStream(
                samplerate=self.actual_sample_rate,
                channels=self.channels,
                dtype=np.int16,
                blocksize=self.actual_chunk_size,
                device=self._get_device_index(config.audio.input_device),
                callback=audio_callback
            )
            self._stream.start()
        else:
            # PyAudio async streaming via thread
            import threading
            
            def pyaudio_thread():
                p = pyaudio.PyAudio()
                stream = p.open(
                    format=pyaudio.paInt16,
                    channels=self.channels,
                    rate=self.actual_sample_rate,
                    input=True,
                    frames_per_buffer=self.actual_chunk_size,
                    input_device_index=self._get_device_index(config.audio.input_device)
                )
                
                while self._is_recording:
                    try:
                        data = stream.read(self.actual_chunk_size, exception_on_overflow=False)
                        # Skip if muted (prevent self-hearing)
                        if self._is_muted:
                            continue
                        # Resample if needed
                        if self._needs_resampling:
                            audio_frame = np.frombuffer(data, dtype=np.int16)
                            audio_float = audio_frame.astype(np.float32)
                            resampled = resample(audio_float, self.chunk_size)
                            data = resampled.astype(np.int16).tobytes()
                        if self._audio_queue:
                            asyncio.run_coroutine_threadsafe(
                                self._audio_queue.put(data),
                                asyncio.get_event_loop()
                            )
                    except Exception as e:
                        logger.error(f"PyAudio Fehler: {e}")
                        break
                
                stream.stop_stream()
                stream.close()
                p.terminate()
            
            self._pyaudio_thread = threading.Thread(target=pyaudio_thread, daemon=True)
            self._pyaudio_thread.start()
        
        logger.info("Audio-Streaming gestartet")
    
    async def stop_streaming(self) -> None:
        """Stop async audio streaming."""
        self._is_recording = False
        
        if self._stream and self._use_sounddevice:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        
        self._audio_queue = None
        logger.info("Audio-Streaming gestoppt")
    
    def mute(self) -> None:
        """Mute microphone input to prevent self-hearing during playback."""
        self._is_muted = True
        logger.debug("Mikrofon gemutet")
    
    def unmute(self) -> None:
        """Unmute microphone input."""
        self._is_muted = False
        logger.debug("Mikrofon entmutet")
    
    async def get_audio_stream(self) -> AsyncGenerator[bytes, None]:
        """
        Async generator yielding audio chunks.
        Used for streaming to Gemini Live API.
        """
        if not self._audio_queue:
            raise RuntimeError("Audio streaming nicht gestartet")
        
        while self._is_recording:
            try:
                audio_data = await asyncio.wait_for(
                    self._audio_queue.get(),
                    timeout=1.0
                )
                yield audio_data
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Audio stream Fehler: {e}")
                break
    
    def cleanup(self) -> None:
        """Clean up audio resources."""
        self._is_recording = False
        
        if self._stream:
            if self._use_sounddevice:
                self._stream.stop()
                self._stream.close()
            else:
                self._stream.stop_stream()
                self._stream.close()
            self._stream = None
        
        if self._pyaudio_instance:
            self._pyaudio_instance.terminate()
            self._pyaudio_instance = None
        
        logger.info("Audio Handler bereinigt")
    
    def list_devices(self) -> list[dict]:
        """List available audio input devices."""
        devices = []
        
        if self._use_sounddevice:
            for i, dev in enumerate(sd.query_devices()):
                if dev['max_input_channels'] > 0:
                    devices.append({
                        'index': i,
                        'name': dev['name'],
                        'channels': dev['max_input_channels'],
                        'sample_rate': dev['default_samplerate']
                    })
        else:
            p = pyaudio.PyAudio()
            for i in range(p.get_device_count()):
                dev = p.get_device_info_by_index(i)
                if dev['maxInputChannels'] > 0:
                    devices.append({
                        'index': i,
                        'name': dev['name'],
                        'channels': dev['maxInputChannels'],
                        'sample_rate': dev['defaultSampleRate']
                    })
            p.terminate()
        
        return devices
