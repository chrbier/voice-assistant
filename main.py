#!/usr/bin/env python3
"""
Voice Assistant - Main Entry Point

A voice-activated assistant using:
- Picovoice Porcupine for offline wakeword detection
- Google Gemini 2.5 Flash Native Audio for conversations
- Google Calendar integration for scheduling

Usage:
    python main.py [--list-devices] [--test-audio]
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.config import config


def setup_logging(verbose: bool = False) -> None:
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    
    # Use colorlog if available
    try:
        import colorlog
        handler = colorlog.StreamHandler()
        handler.setFormatter(colorlog.ColoredFormatter(
            '%(log_color)s%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            log_colors={
                'DEBUG': 'cyan',
                'INFO': 'green',
                'WARNING': 'yellow',
                'ERROR': 'red',
                'CRITICAL': 'red,bg_white',
            }
        ))
        logging.root.handlers = [handler]
        logging.root.setLevel(level)
    except ImportError:
        logging.basicConfig(
            level=level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )


def list_audio_devices() -> None:
    """List all available audio devices."""
    from src.audio.handler import AudioHandler
    from src.audio.player import AudioPlayer
    
    print("\n=== Audio-Eingabegeräte ===")
    handler = AudioHandler()
    for dev in handler.list_devices():
        print(f"  [{dev['index']}] {dev['name']}")
        print(f"      Kanäle: {dev['channels']}, Sample-Rate: {dev['sample_rate']}")
    
    print("\n=== Audio-Ausgabegeräte ===")
    player = AudioPlayer()
    for dev in player.list_devices():
        print(f"  [{dev['index']}] {dev['name']}")
        print(f"      Kanäle: {dev['channels']}, Sample-Rate: {dev['sample_rate']}")
    
    print("\nTipp: Setze AUDIO_INPUT_DEVICE und AUDIO_OUTPUT_DEVICE in .env")


def test_audio() -> None:
    """Test audio input and output."""
    from src.audio.handler import AudioHandler
    from src.audio.player import AudioPlayer
    import numpy as np
    
    print("\n=== Audio-Test ===")
    
    # Test output
    print("\n1. Teste Audio-Ausgabe (Beep)...")
    player = AudioPlayer()
    player._play_beep(frequency=440, duration=0.3)
    player._play_beep(frequency=880, duration=0.3)
    print("   ✓ Audio-Ausgabe funktioniert")
    
    # Test input
    print("\n2. Teste Audio-Eingabe (3 Sekunden)...")
    print("   Bitte sprich etwas ins Mikrofon...")
    
    handler = AudioHandler()
    frames = []
    for i in range(int(3 * 16000 / 512)):  # 3 seconds
        frame = handler.get_audio_frame_sync()
        frames.append(frame)
    
    audio_data = np.concatenate(frames)
    max_amplitude = np.max(np.abs(audio_data))
    
    print(f"   Maximale Amplitude: {max_amplitude}")
    if max_amplitude > 1000:
        print("   ✓ Audio-Eingabe funktioniert")
    else:
        print("   ⚠ Sehr leises Signal - prüfe Mikrofon")
    
    handler.cleanup()
    player.cleanup()
    print("\n=== Test abgeschlossen ===")


def test_wakeword() -> None:
    """Test wakeword detection."""
    from src.wakeword.detector import WakewordDetector
    import numpy as np
    
    try:
        import sounddevice as sd
        use_sounddevice = True
    except OSError:
        import pyaudio
        use_sounddevice = False
    
    print("\n=== Wakeword-Test ===")
    
    # Initialize detector first to get frame length
    detected = False
    def on_wakeword():
        nonlocal detected
        detected = True
        print("\n✓ Wakeword erkannt!")
    
    detector = WakewordDetector(on_wakeword=on_wakeword)
    detector.initialize()
    
    # Get required frame length from Porcupine
    frame_length = detector.frame_length
    sample_rate = detector.sample_rate
    
    print(f"Porcupine Frame-Länge: {frame_length}")
    print(f"Porcupine Sample-Rate: {sample_rate}")
    print(f"\nSage '{config.porcupine.keyword}' um die Erkennung zu testen...")
    print("(Drücke Ctrl+C zum Beenden)\n")
    
    detector.start()
    
    # Set up audio input with correct frame length
    if use_sounddevice:
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
    
    frame_count = 0
    try:
        while not detected:
            if use_sounddevice:
                audio_data, overflowed = stream.read(frame_length)
                frame = audio_data.flatten()
            else:
                data = stream.read(frame_length, exception_on_overflow=False)
                frame = np.frombuffer(data, dtype=np.int16)
            
            # Show audio level every 50 frames (~1.6s)
            frame_count += 1
            if frame_count % 50 == 0:
                level = np.max(np.abs(frame))
                bars = '█' * min(int(level / 1000), 30)
                print(f"\rAudio-Level: {level:5d} {bars:<30}", end='', flush=True)
            
            detector.process_frame(frame)
            
    except KeyboardInterrupt:
        print("\nAbgebrochen")
    finally:
        if use_sounddevice:
            stream.stop()
            stream.close()
        else:
            stream.stop_stream()
            stream.close()
            p.terminate()
        detector.cleanup()


async def run_assistant() -> None:
    """Run the main assistant."""
    from src.assistant import VoiceAssistant
    
    assistant = VoiceAssistant()
    
    try:
        await assistant.initialize()
        await assistant.run()
    except KeyboardInterrupt:
        pass
    finally:
        await assistant.stop()


def main():
    """Main entry point with argument parsing."""
    parser = argparse.ArgumentParser(
        description="Voice Assistant mit Gemini Native Audio",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Beispiele:
  python main.py                    # Starte den Assistenten
  python main.py --list-devices     # Zeige Audio-Geräte
  python main.py --test-audio       # Teste Audio I/O
  python main.py --test-wakeword    # Teste Wakeword-Erkennung
  python main.py -v                 # Verbose-Modus
        """
    )
    
    parser.add_argument(
        '--list-devices',
        action='store_true',
        help='Liste alle Audio-Geräte auf'
    )
    parser.add_argument(
        '--test-audio',
        action='store_true',
        help='Teste Audio Ein-/Ausgabe'
    )
    parser.add_argument(
        '--test-wakeword',
        action='store_true',
        help='Teste Wakeword-Erkennung'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Aktiviere Debug-Logging'
    )
    
    args = parser.parse_args()
    
    setup_logging(args.verbose)
    
    if args.list_devices:
        list_audio_devices()
        return
    
    if args.test_audio:
        test_audio()
        return
    
    if args.test_wakeword:
        test_wakeword()
        return
    
    # Run main assistant
    try:
        asyncio.run(run_assistant())
    except KeyboardInterrupt:
        print("\nBeendet.")


if __name__ == "__main__":
    main()
