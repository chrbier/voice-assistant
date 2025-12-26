"""
Wakeword detection using Picovoice Porcupine.
Runs completely offline on Raspberry Pi.
"""

import logging
from typing import Callable, Optional
import numpy as np

try:
    import pvporcupine
except ImportError:
    pvporcupine = None
    logging.warning("pvporcupine nicht installiert - Wakeword-Erkennung deaktiviert")

from src.config import config

logger = logging.getLogger(__name__)


class WakewordDetector:
    """
    Offline wakeword detection using Picovoice Porcupine.
    Listens for "Computer" keyword and triggers callback.
    """
    
    def __init__(self, on_wakeword: Optional[Callable[[], None]] = None):
        """
        Initialize wakeword detector.
        
        Args:
            on_wakeword: Callback function to call when wakeword is detected
        """
        self.on_wakeword = on_wakeword
        self._porcupine = None
        self._is_running = False
        
        if pvporcupine is None:
            raise RuntimeError("pvporcupine Bibliothek nicht verfügbar")
    
    def initialize(self) -> None:
        """Initialize Porcupine engine."""
        try:
            # Use built-in "computer" keyword
            self._porcupine = pvporcupine.create(
                access_key=config.porcupine.access_key,
                keywords=[config.porcupine.keyword],
                sensitivities=[config.porcupine.sensitivity]
            )
            
            logger.info(f"Porcupine initialisiert - Wakeword: '{config.porcupine.keyword}'")
            logger.info(f"Frame-Länge: {self._porcupine.frame_length}, Sample-Rate: {self._porcupine.sample_rate}")
            
        except pvporcupine.PorcupineError as e:
            logger.error(f"Porcupine Initialisierungsfehler: {e}")
            raise
    
    @property
    def frame_length(self) -> int:
        """Get required audio frame length."""
        if self._porcupine:
            return self._porcupine.frame_length
        return 512  # Default Porcupine frame length
    
    @property
    def sample_rate(self) -> int:
        """Get required sample rate."""
        if self._porcupine:
            return self._porcupine.sample_rate
        return 16000  # Default Porcupine sample rate
    
    def process_frame(self, audio_frame: np.ndarray) -> bool:
        """
        Process a single audio frame for wakeword detection.
        
        Args:
            audio_frame: numpy array of int16 audio samples
            
        Returns:
            True if wakeword was detected, False otherwise
        """
        if self._porcupine is None:
            return False
        
        # Ensure correct frame length
        if len(audio_frame) != self._porcupine.frame_length:
            logger.warning(f"Falsche Frame-Länge: {len(audio_frame)}, erwartet: {self._porcupine.frame_length}")
            return False
        
        # Process frame
        keyword_index = self._porcupine.process(audio_frame)
        
        if keyword_index >= 0:
            logger.info(f"🎤 Wakeword '{config.porcupine.keyword}' erkannt!")
            
            if self.on_wakeword:
                self.on_wakeword()
            
            return True
        
        return False
    
    def start(self) -> None:
        """Mark detector as running."""
        self._is_running = True
        logger.info("Wakeword-Erkennung gestartet - warte auf 'Computer'...")
    
    def stop(self) -> None:
        """Stop the detector."""
        self._is_running = False
        logger.info("Wakeword-Erkennung gestoppt")
    
    @property
    def is_running(self) -> bool:
        """Check if detector is running."""
        return self._is_running
    
    def cleanup(self) -> None:
        """Clean up Porcupine resources."""
        self._is_running = False
        
        if self._porcupine:
            self._porcupine.delete()
            self._porcupine = None
            logger.info("Porcupine bereinigt")
