"""
Timer Tool for countdown timers with alarm.
Supports multiple named timers, pause/resume, and alarm sounds.
"""

import logging
import threading
import time
import os
import numpy as np
from datetime import datetime, timedelta
from typing import Optional, Callable, Dict
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class Timer:
    """Single timer instance."""
    name: str
    duration_seconds: int
    remaining_seconds: float
    start_time: datetime
    is_running: bool = True
    is_paused: bool = False
    thread: Optional[threading.Thread] = field(default=None, repr=False)


class TimerTool:
    """
    Timer management with countdown and alarm functionality.
    Supports multiple concurrent timers.
    """
    
    def __init__(self, audio_player=None):
        self._timers: Dict[str, Timer] = {}
        self._audio_player = audio_player
        self._alarm_sound_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "sounds", "alarm.wav"
        )
        self._lock = threading.Lock()
    
    def initialize(self) -> None:
        """Initialize timer tool and generate alarm sound if needed."""
        # Generate alarm sound if it doesn't exist
        if not os.path.exists(self._alarm_sound_path):
            self._generate_alarm_sound()
        logger.info("✓ Timer-Tool initialisiert")
    
    def _generate_alarm_sound(self) -> None:
        """Generate a pleasant alarm sound."""
        try:
            from scipy.io import wavfile
            
            sample_rate = 24000
            duration = 2.0  # seconds
            
            t = np.linspace(0, duration, int(sample_rate * duration), False)
            
            # Create a pleasant chime pattern (three ascending tones)
            frequencies = [523.25, 659.25, 783.99]  # C5, E5, G5 (C major chord)
            
            audio = np.zeros_like(t)
            
            for i, freq in enumerate(frequencies):
                start = i * 0.3
                end = start + 0.5
                mask = (t >= start) & (t < end)
                
                # Envelope for smooth sound
                segment_t = t[mask] - start
                envelope = np.sin(np.pi * segment_t / 0.5)  # Smooth envelope
                
                tone = np.sin(2 * np.pi * freq * t[mask]) * envelope
                audio[mask] += tone
            
            # Add a final combined chord
            chord_start = 1.0
            chord_mask = t >= chord_start
            chord_t = t[chord_mask] - chord_start
            chord_envelope = np.exp(-chord_t * 2)  # Decay
            
            for freq in frequencies:
                audio[chord_mask] += np.sin(2 * np.pi * freq * t[chord_mask]) * chord_envelope * 0.5
            
            # Normalize
            audio = audio / np.max(np.abs(audio)) * 0.7
            audio_int16 = (audio * 32767).astype(np.int16)
            
            # Ensure sounds directory exists
            os.makedirs(os.path.dirname(self._alarm_sound_path), exist_ok=True)
            
            wavfile.write(self._alarm_sound_path, sample_rate, audio_int16)
            logger.info(f"✓ Alarm-Sound erstellt: {self._alarm_sound_path}")
            
        except Exception as e:
            logger.warning(f"Konnte Alarm-Sound nicht erstellen: {e}")
    
    def _play_alarm(self, timer_name: str) -> None:
        """Play alarm sound when timer expires."""
        logger.info(f"⏰ ALARM: Timer '{timer_name}' ist abgelaufen!")
        
        if self._audio_player and os.path.exists(self._alarm_sound_path):
            try:
                # Play alarm sound 3 times
                for _ in range(3):
                    self._audio_player.play_sound(self._alarm_sound_path)
                    time.sleep(0.5)
            except Exception as e:
                logger.error(f"Fehler beim Abspielen des Alarms: {e}")
    
    def _timer_thread(self, timer_name: str) -> None:
        """Background thread for a single timer."""
        while True:
            with self._lock:
                if timer_name not in self._timers:
                    return
                
                timer = self._timers[timer_name]
                
                if not timer.is_running:
                    return
                
                if timer.is_paused:
                    time.sleep(0.1)
                    continue
                
                # Update remaining time
                elapsed = (datetime.now() - timer.start_time).total_seconds()
                timer.remaining_seconds = timer.duration_seconds - elapsed
                
                if timer.remaining_seconds <= 0:
                    # Timer expired
                    timer.is_running = False
                    del self._timers[timer_name]
                    break
            
            time.sleep(0.1)
        
        # Play alarm
        self._play_alarm(timer_name)
    
    def _format_duration(self, seconds: float) -> str:
        """Format seconds to human-readable string."""
        seconds = max(0, int(seconds))
        
        if seconds >= 3600:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            secs = seconds % 60
            if secs > 0:
                return f"{hours} Stunden, {minutes} Minuten und {secs} Sekunden"
            elif minutes > 0:
                return f"{hours} Stunden und {minutes} Minuten"
            else:
                return f"{hours} Stunden"
        elif seconds >= 60:
            minutes = seconds // 60
            secs = seconds % 60
            if secs > 0:
                return f"{minutes} Minuten und {secs} Sekunden"
            else:
                return f"{minutes} Minuten"
        else:
            return f"{seconds} Sekunden"
    
    def _parse_duration(self, minutes: int = 0, seconds: int = 0, hours: int = 0) -> int:
        """Convert hours/minutes/seconds to total seconds."""
        return hours * 3600 + minutes * 60 + seconds
    
    def _generate_timer_name(self) -> str:
        """Generate a unique timer name."""
        count = len(self._timers) + 1
        name = f"Timer {count}"
        while name in self._timers:
            count += 1
            name = f"Timer {count}"
        return name
    
    # === Tool Functions for Gemini ===
    
    def set_timer(self, minutes: int = 0, seconds: int = 0, hours: int = 0, name: str = "") -> str:
        """
        Set a new countdown timer.
        
        Args:
            minutes: Minutes for the timer
            seconds: Seconds for the timer  
            hours: Hours for the timer
            name: Optional name for the timer
            
        Returns:
            Status message
        """
        total_seconds = self._parse_duration(minutes, seconds, hours)
        
        if total_seconds <= 0:
            return "Bitte gib eine gültige Zeit an (z.B. 5 Minuten)."
        
        if total_seconds > 24 * 3600:
            return "Timer kann maximal 24 Stunden lang sein."
        
        timer_name = name.strip() if name else self._generate_timer_name()
        
        # Check if timer with same name exists
        with self._lock:
            if timer_name in self._timers:
                return f"Ein Timer mit dem Namen '{timer_name}' läuft bereits. Stoppe ihn zuerst oder wähle einen anderen Namen."
        
        # Create timer
        timer = Timer(
            name=timer_name,
            duration_seconds=total_seconds,
            remaining_seconds=total_seconds,
            start_time=datetime.now()
        )
        
        with self._lock:
            self._timers[timer_name] = timer
        
        # Start background thread
        thread = threading.Thread(target=self._timer_thread, args=(timer_name,), daemon=True)
        timer.thread = thread
        thread.start()
        
        duration_str = self._format_duration(total_seconds)
        logger.info(f"⏱ Timer '{timer_name}' gestartet: {duration_str}")
        
        return f"Timer '{timer_name}' auf {duration_str} gestellt."
    
    def stop_timer(self, name: str = "") -> str:
        """
        Stop and remove a timer.
        
        Args:
            name: Name of the timer to stop (empty = stop all or first timer)
            
        Returns:
            Status message
        """
        with self._lock:
            if not self._timers:
                return "Es läuft kein Timer."
            
            if name:
                # Stop specific timer
                if name not in self._timers:
                    available = ", ".join(self._timers.keys())
                    return f"Timer '{name}' nicht gefunden. Aktive Timer: {available}"
                
                timer = self._timers.pop(name)
                timer.is_running = False
                logger.info(f"⏱ Timer '{name}' gestoppt")
                return f"Timer '{name}' gestoppt."
            
            elif len(self._timers) == 1:
                # Stop the only timer
                timer_name = list(self._timers.keys())[0]
                timer = self._timers.pop(timer_name)
                timer.is_running = False
                logger.info(f"⏱ Timer '{timer_name}' gestoppt")
                return f"Timer '{timer_name}' gestoppt."
            
            else:
                # Multiple timers - stop all
                count = len(self._timers)
                for timer in self._timers.values():
                    timer.is_running = False
                self._timers.clear()
                logger.info(f"⏱ {count} Timer gestoppt")
                return f"Alle {count} Timer gestoppt."
    
    def get_timer_status(self, name: str = "") -> str:
        """
        Get status of timer(s).
        
        Args:
            name: Name of specific timer (empty = all timers)
            
        Returns:
            Status message
        """
        with self._lock:
            if not self._timers:
                return "Es läuft kein Timer."
            
            if name:
                if name not in self._timers:
                    return f"Timer '{name}' nicht gefunden."
                
                timer = self._timers[name]
                remaining = self._format_duration(timer.remaining_seconds)
                status = "pausiert" if timer.is_paused else "läuft"
                return f"Timer '{name}': {remaining} verbleibend ({status})"
            
            else:
                # All timers
                statuses = []
                for timer in self._timers.values():
                    remaining = self._format_duration(timer.remaining_seconds)
                    status = "pausiert" if timer.is_paused else "läuft"
                    statuses.append(f"'{timer.name}': {remaining} ({status})")
                
                return "Aktive Timer: " + ", ".join(statuses)
    
    def pause_timer(self, name: str = "") -> str:
        """
        Pause a running timer.
        
        Args:
            name: Name of timer to pause
            
        Returns:
            Status message
        """
        with self._lock:
            if not self._timers:
                return "Es läuft kein Timer."
            
            timer_name = name if name else (list(self._timers.keys())[0] if len(self._timers) == 1 else "")
            
            if not timer_name:
                return "Bitte gib an, welchen Timer du pausieren möchtest."
            
            if timer_name not in self._timers:
                return f"Timer '{timer_name}' nicht gefunden."
            
            timer = self._timers[timer_name]
            
            if timer.is_paused:
                return f"Timer '{timer_name}' ist bereits pausiert."
            
            timer.is_paused = True
            # Save remaining time
            elapsed = (datetime.now() - timer.start_time).total_seconds()
            timer.remaining_seconds = timer.duration_seconds - elapsed
            
            logger.info(f"⏸ Timer '{timer_name}' pausiert")
            return f"Timer '{timer_name}' pausiert. Verbleibend: {self._format_duration(timer.remaining_seconds)}"
    
    def resume_timer(self, name: str = "") -> str:
        """
        Resume a paused timer.
        
        Args:
            name: Name of timer to resume
            
        Returns:
            Status message
        """
        with self._lock:
            if not self._timers:
                return "Es läuft kein Timer."
            
            timer_name = name if name else (list(self._timers.keys())[0] if len(self._timers) == 1 else "")
            
            if not timer_name:
                return "Bitte gib an, welchen Timer du fortsetzen möchtest."
            
            if timer_name not in self._timers:
                return f"Timer '{timer_name}' nicht gefunden."
            
            timer = self._timers[timer_name]
            
            if not timer.is_paused:
                return f"Timer '{timer_name}' läuft bereits."
            
            timer.is_paused = False
            # Reset start time based on remaining time
            timer.start_time = datetime.now()
            timer.duration_seconds = timer.remaining_seconds
            
            logger.info(f"▶ Timer '{timer_name}' fortgesetzt")
            return f"Timer '{timer_name}' fortgesetzt. Verbleibend: {self._format_duration(timer.remaining_seconds)}"
    
    def add_time(self, minutes: int = 0, seconds: int = 0, name: str = "") -> str:
        """
        Add time to an existing timer.
        
        Args:
            minutes: Minutes to add
            seconds: Seconds to add
            name: Timer name
            
        Returns:
            Status message
        """
        additional_seconds = minutes * 60 + seconds
        
        if additional_seconds <= 0:
            return "Bitte gib an, wie viel Zeit hinzugefügt werden soll."
        
        with self._lock:
            if not self._timers:
                return "Es läuft kein Timer."
            
            timer_name = name if name else (list(self._timers.keys())[0] if len(self._timers) == 1 else "")
            
            if not timer_name:
                return "Bitte gib an, zu welchem Timer Zeit hinzugefügt werden soll."
            
            if timer_name not in self._timers:
                return f"Timer '{timer_name}' nicht gefunden."
            
            timer = self._timers[timer_name]
            timer.duration_seconds += additional_seconds
            
            added_str = self._format_duration(additional_seconds)
            new_remaining = self._format_duration(timer.remaining_seconds + additional_seconds)
            
            logger.info(f"⏱ Timer '{timer_name}': +{added_str}")
            return f"{added_str} zu Timer '{timer_name}' hinzugefügt. Neue verbleibende Zeit: {new_remaining}"
    
    def get_tool_definitions(self) -> list[dict]:
        """Return tool definitions for Gemini."""
        return [
            {
                "name": "set_timer",
                "description": "Setzt einen Countdown-Timer. Nach Ablauf ertönt ein Alarm. Beispiel: 'Timer auf 5 Minuten' oder 'Stelle einen Eier-Timer auf 7 Minuten'",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "minutes": {
                            "type": "integer",
                            "description": "Minuten für den Timer"
                        },
                        "seconds": {
                            "type": "integer",
                            "description": "Sekunden für den Timer"
                        },
                        "hours": {
                            "type": "integer",
                            "description": "Stunden für den Timer"
                        },
                        "name": {
                            "type": "string",
                            "description": "Optionaler Name für den Timer (z.B. 'Nudeln', 'Eier')"
                        }
                    }
                }
            },
            {
                "name": "stop_timer",
                "description": "Stoppt einen laufenden Timer. Beispiel: 'Stoppe den Timer' oder 'Timer abbrechen'",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Name des Timers (leer = alle Timer stoppen)"
                        }
                    }
                }
            },
            {
                "name": "timer_status",
                "description": "Zeigt die verbleibende Zeit des Timers. Beispiel: 'Wie lange läuft der Timer noch?'",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Name des Timers (leer = alle Timer)"
                        }
                    }
                }
            },
            {
                "name": "pause_timer",
                "description": "Pausiert einen laufenden Timer. Beispiel: 'Pausiere den Timer'",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Name des Timers"
                        }
                    }
                }
            },
            {
                "name": "resume_timer",
                "description": "Setzt einen pausierten Timer fort. Beispiel: 'Timer fortsetzen'",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Name des Timers"
                        }
                    }
                }
            },
            {
                "name": "add_timer_time",
                "description": "Fügt Zeit zu einem laufenden Timer hinzu. Beispiel: 'Füge 2 Minuten zum Timer hinzu'",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "minutes": {
                            "type": "integer",
                            "description": "Minuten hinzufügen"
                        },
                        "seconds": {
                            "type": "integer",
                            "description": "Sekunden hinzufügen"
                        },
                        "name": {
                            "type": "string",
                            "description": "Name des Timers"
                        }
                    }
                }
            }
        ]
    
    def get_tool_handlers(self) -> dict[str, Callable]:
        """Return mapping of tool names to handler functions."""
        return {
            "set_timer": self.set_timer,
            "stop_timer": self.stop_timer,
            "timer_status": self.get_timer_status,
            "pause_timer": self.pause_timer,
            "resume_timer": self.resume_timer,
            "add_timer_time": self.add_time,
        }
    
    def cleanup(self) -> None:
        """Stop all timers."""
        with self._lock:
            for timer in self._timers.values():
                timer.is_running = False
            self._timers.clear()
