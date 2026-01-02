"""
Audio player with continuous buffer for seamless Gemini audio streaming.
Prevents chunk overlap and audio glitches.
"""

import logging
import threading
import wave
import time
from pathlib import Path
from typing import Optional
import numpy as np
from scipy.signal import resample

try:
    import sounddevice as sd
    _use_sounddevice = True
except OSError:
    sd = None
    import pyaudio
    _use_sounddevice = False

from src.config import config

logger = logging.getLogger(__name__)


class AudioPlayer:
    """
    Audio player using a continuous sample buffer.
    All incoming chunks are appended sequentially and played back smoothly.
    """
    
    def __init__(self):
        self.target_sample_rate = config.gemini.output_sample_rate  # 24kHz from Gemini
        self.channels = 1
        self._is_playing = False
        self._playback_thread: Optional[threading.Thread] = None
        
        # Continuous sample buffer (numpy array)
        self._samples = np.array([], dtype=np.int16)
        self._buffer_lock = threading.Lock()
        self._read_index = 0
        
        # Pre-buffer settings
        self._prebuffer_samples = 2400  # 100ms at 24kHz before starting playback
        self._playback_started = False
        
        # Chunk size for playback (samples per write)
        self._chunk_samples = 1200  # 50ms chunks
        
        # Check what sample rate the speaker actually supports
        self.actual_sample_rate, self._needs_resampling = self._check_supported_output_rate()
        if self._needs_resampling:
            self._resample_ratio = self.actual_sample_rate / self.target_sample_rate
            self._actual_chunk_samples = int(self._chunk_samples * self._resample_ratio)
            logger.info(f"Audio-Player: Lautsprecher bei {self.actual_sample_rate} Hz, Resampling von {self.target_sample_rate} Hz")
        else:
            self.actual_sample_rate = self.target_sample_rate
            self._actual_chunk_samples = self._chunk_samples
    
    def _check_supported_output_rate(self) -> tuple[int, bool]:
        """Check if target sample rate is supported for output, return (actual_rate, needs_resampling)."""
        if _use_sounddevice and sd is not None:
            try:
                sd.check_output_settings(samplerate=self.target_sample_rate)
                return self.target_sample_rate, False
            except Exception:
                # Try common rates that might be supported
                for rate in [48000, 44100]:
                    try:
                        sd.check_output_settings(samplerate=rate)
                        return rate, True
                    except Exception:
                        continue
        return self.target_sample_rate, False
        
    def _get_device_index(self, device_name: str) -> Optional[int]:
        """Get output device index by name."""
        if device_name == "default":
            return None
            
        if _use_sounddevice:
            devices = sd.query_devices()
            for i, dev in enumerate(devices):
                if device_name.lower() in dev['name'].lower() and dev['max_output_channels'] > 0:
                    return i
        else:
            p = pyaudio.PyAudio()
            for i in range(p.get_device_count()):
                dev = p.get_device_info_by_index(i)
                if device_name.lower() in dev['name'].lower() and dev['maxOutputChannels'] > 0:
                    p.terminate()
                    return i
            p.terminate()
        return None
    
    def play_sound(self, sound_file: str) -> None:
        """Play a WAV sound file synchronously."""
        sound_path = config.assistant.sounds_dir / sound_file
        
        if not sound_path.exists():
            logger.warning(f"Sound-Datei nicht gefunden: {sound_path}")
            self._play_beep()
            return
        
        try:
            with wave.open(str(sound_path), 'rb') as wf:
                sr = wf.getframerate()
                ch = wf.getnchannels()
                data = wf.readframes(wf.getnframes())
                arr = np.frombuffer(data, dtype=np.int16)
                if ch == 2:
                    arr = arr.reshape(-1, 2).mean(axis=1).astype(np.int16)
                
                # Resample to supported rate if needed
                if sr != self.actual_sample_rate:
                    target_samples = int(len(arr) * self.actual_sample_rate / sr)
                    arr_float = arr.astype(np.float32)
                    arr = resample(arr_float, target_samples).astype(np.int16)
                    sr = self.actual_sample_rate
                
                if _use_sounddevice:
                    sd.play(arr, sr, device=self._get_device_index(config.audio.output_device))
                    sd.wait()
                else:
                    p = pyaudio.PyAudio()
                    stream = p.open(format=pyaudio.paInt16, channels=1, rate=sr, output=True,
                                   output_device_index=self._get_device_index(config.audio.output_device))
                    stream.write(arr.tobytes())
                    stream.stop_stream()
                    stream.close()
                    p.terminate()
        except Exception as e:
            logger.error(f"Fehler beim Abspielen: {e}")
            self._play_beep()
    
    def _play_beep(self, freq: int = 800, dur: float = 0.15) -> None:
        """Play a simple beep."""
        # Use actual supported sample rate
        sr = self.actual_sample_rate if self.actual_sample_rate else 48000
        t = np.linspace(0, dur, int(sr * dur), False)
        tone = (np.sin(2 * np.pi * freq * t) * 16000).astype(np.int16)
        try:
            if _use_sounddevice:
                sd.play(tone, sr)
                sd.wait()
            else:
                p = pyaudio.PyAudio()
                s = p.open(format=pyaudio.paInt16, channels=1, rate=sr, output=True)
                s.write(tone.tobytes())
                s.stop_stream()
                s.close()
                p.terminate()
        except Exception as e:
            logger.debug(f"Beep fehlgeschlagen: {e}")
    
    def play_activation_sound(self) -> None:
        """Play wakeword activation sound."""
        self.play_sound(config.assistant.activation_sound)
    
    def play_deactivation_sound(self) -> None:
        """Play conversation end sound."""
        self.play_sound(config.assistant.deactivation_sound)
    
    def start_playback(self) -> None:
        """Start the playback system."""
        with self._buffer_lock:
            self._samples = np.array([], dtype=np.int16)
            self._read_index = 0
        
        self._playback_started = False
        self._is_playing = True
        
        self._playback_thread = threading.Thread(target=self._playback_loop, daemon=True)
        self._playback_thread.start()
        logger.info("Audio-Playback gestartet")
    
    def _playback_loop(self) -> None:
        """Main playback loop."""
        if _use_sounddevice:
            self._playback_sounddevice()
        else:
            self._playback_pyaudio()
    
    def _playback_sounddevice(self) -> None:
        """Sounddevice playback."""
        try:
            with sd.OutputStream(
                samplerate=self.actual_sample_rate,
                channels=1,
                dtype=np.int16,
                blocksize=self._actual_chunk_samples,
                device=self._get_device_index(config.audio.output_device)
            ) as stream:
                while self._is_playing:
                    chunk = self._get_samples(self._chunk_samples)
                    if chunk is not None and len(chunk) > 0:
                        # Resample if needed (e.g., 24kHz -> 48kHz)
                        if self._needs_resampling:
                            chunk_float = chunk.astype(np.float32)
                            resampled = resample(chunk_float, self._actual_chunk_samples)
                            chunk = resampled.astype(np.int16)
                        # Pad if needed
                        if len(chunk) < self._actual_chunk_samples:
                            chunk = np.pad(chunk, (0, self._actual_chunk_samples - len(chunk)))
                        stream.write(chunk.reshape(-1, 1))
                    else:
                        time.sleep(0.01)
        except Exception as e:
            logger.error(f"Sounddevice error: {e}")
    
    def _playback_pyaudio(self) -> None:
        """PyAudio playback."""
        p = pyaudio.PyAudio()
        try:
            stream = p.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=self.actual_sample_rate,
                output=True,
                frames_per_buffer=self._actual_chunk_samples,
                output_device_index=self._get_device_index(config.audio.output_device)
            )
            
            while self._is_playing:
                chunk = self._get_samples(self._chunk_samples)
                if chunk is not None and len(chunk) > 0:
                    # Resample if needed (e.g., 24kHz -> 48kHz)
                    if self._needs_resampling:
                        chunk_float = chunk.astype(np.float32)
                        resampled = resample(chunk_float, self._actual_chunk_samples)
                        chunk = resampled.astype(np.int16)
                    stream.write(chunk.tobytes())
                else:
                    time.sleep(0.01)
            
            stream.stop_stream()
            stream.close()
        except Exception as e:
            logger.error(f"PyAudio error: {e}")
        finally:
            p.terminate()
    
    def _get_samples(self, count: int) -> Optional[np.ndarray]:
        """Get next samples from buffer."""
        with self._buffer_lock:
            available = len(self._samples) - self._read_index
            
            # Pre-buffering check
            if not self._playback_started:
                if available >= self._prebuffer_samples:
                    self._playback_started = True
                    logger.debug("Pre-buffer voll, starte Wiedergabe")
                else:
                    return None
            
            if available <= 0:
                return None
            
            # Get chunk
            end = min(self._read_index + count, len(self._samples))
            chunk = self._samples[self._read_index:end].copy()
            self._read_index = end
            
            # Compact buffer periodically to prevent memory growth
            if self._read_index > 48000:  # 2 seconds worth
                self._samples = self._samples[self._read_index:]
                self._read_index = 0
            
            return chunk
    
    def queue_audio(self, audio_data: bytes) -> None:
        """Add audio data to buffer. Thread-safe."""
        if not self._is_playing:
            return
        
        new_samples = np.frombuffer(audio_data, dtype=np.int16)
        
        with self._buffer_lock:
            self._samples = np.concatenate([self._samples, new_samples])
    
    def stop_playback(self) -> None:
        """Stop playback."""
        self._is_playing = False
        
        if self._playback_thread and self._playback_thread.is_alive():
            self._playback_thread.join(timeout=1.0)
        
        with self._buffer_lock:
            self._samples = np.array([], dtype=np.int16)
            self._read_index = 0
        
        self._playback_started = False
        logger.info("Audio-Playback gestoppt")
    
    # Async wrappers
    async def start_playback_stream(self) -> None:
        self.start_playback()
    
    async def stop_playback_stream(self) -> None:
        self.stop_playback()
    
    def cleanup(self) -> None:
        self.stop_playback()
        logger.info("Audio Player bereinigt")
    
    def list_devices(self) -> list[dict]:
        """List audio output devices."""
        devices = []
        if _use_sounddevice:
            for i, dev in enumerate(sd.query_devices()):
                if dev['max_output_channels'] > 0:
                    devices.append({'index': i, 'name': dev['name'],
                                   'channels': dev['max_output_channels'],
                                   'sample_rate': dev['default_samplerate']})
        else:
            p = pyaudio.PyAudio()
            for i in range(p.get_device_count()):
                dev = p.get_device_info_by_index(i)
                if dev['maxOutputChannels'] > 0:
                    devices.append({'index': i, 'name': dev['name'],
                                   'channels': dev['maxOutputChannels'],
                                   'sample_rate': dev['defaultSampleRate']})
            p.terminate()
        return devices
