#!/usr/bin/env python3
"""
Generate activation sound for the voice assistant.
Creates a pleasant beep tone as WAV file.
"""

import wave
import struct
import math
from pathlib import Path


def generate_activation_sound(
    filename: str = "activation.wav",
    sample_rate: int = 24000,
    volume: float = 0.5
) -> None:
    """
    Generate a Star Trek-style chirp activation sound.
    Classic TNG communicator chirp: quick ascending two-tone beep.
    """
    output_path = Path(__file__).parent.parent / "sounds" / filename
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    samples = []
    
    # Star Trek TNG style chirp - quick ascending tones
    # First chirp: A5 (880 Hz) -> E6 (1318 Hz)
    tones = [
        (880, 0.06),   # A5 - short
        (1318, 0.08),  # E6 - slightly longer
    ]
    
    for freq, duration in tones:
        num_samples = int(duration * sample_rate)
        for i in range(num_samples):
            t = i / sample_rate
            
            # Sharp attack, quick decay envelope
            attack = 0.008
            decay_start = duration * 0.3
            
            if t < attack:
                envelope = t / attack
            elif t > decay_start:
                envelope = 1.0 - ((t - decay_start) / (duration - decay_start)) * 0.7
            else:
                envelope = 1.0
            
            # Add slight harmonic for richness
            sample = (
                math.sin(2 * math.pi * freq * t) * 0.7 +
                math.sin(2 * math.pi * freq * 2 * t) * 0.2 +
                math.sin(2 * math.pi * freq * 3 * t) * 0.1
            ) * volume * envelope
            samples.append(sample)
        
        # Tiny gap between tones
        gap_samples = int(0.01 * sample_rate)
        samples.extend([0.0] * gap_samples)
    
    # Convert to 16-bit PCM
    pcm_samples = [max(-32768, min(32767, int(s * 32767))) for s in samples]
    
    # Write WAV file
    with wave.open(str(output_path), 'w') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        
        for sample in pcm_samples:
            wav_file.writeframes(struct.pack('<h', sample))
    
    print(f"✓ Star Trek Aktivierungston erstellt: {output_path}")
    print(f"  Dauer: {len(samples) / sample_rate:.2f}s")


def generate_deactivation_sound(
    filename: str = "deactivation.wav",
    frequency1: float = 800,
    frequency2: float = 500,
    duration: float = 0.1,
    sample_rate: int = 24000,
    volume: float = 0.3
) -> None:
    """Generate a descending two-tone deactivation sound."""
    output_path = Path(__file__).parent.parent / "sounds" / filename
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    samples = []
    
    # Generate descending tones
    for freq in [frequency1, frequency2]:
        num_samples = int(duration * sample_rate)
        for i in range(num_samples):
            t = i / sample_rate
            envelope = 1.0
            fade_duration = 0.015
            if t < fade_duration:
                envelope = t / fade_duration
            elif t > duration - fade_duration:
                envelope = (duration - t) / fade_duration
            
            sample = math.sin(2 * math.pi * freq * t) * volume * envelope
            samples.append(sample)
        
        # Small gap
        gap_samples = int(0.03 * sample_rate)
        samples.extend([0.0] * gap_samples)
    
    # Convert to 16-bit PCM
    pcm_samples = [max(-32768, min(32767, int(s * 32767))) for s in samples]
    
    # Write WAV file
    with wave.open(str(output_path), 'w') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        
        for sample in pcm_samples:
            wav_file.writeframes(struct.pack('<h', sample))
    
    print(f"✓ Deaktivierungston erstellt: {output_path}")


if __name__ == "__main__":
    print("Generiere Sound-Dateien...\n")
    generate_activation_sound()
    generate_deactivation_sound()
    print("\nFertig!")
