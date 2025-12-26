# 🎙️ Voice Assistant

Ein KI-Sprachassistent mit Wakeword-Aktivierung, der Google Gemini 2.5 Flash Native Audio für natürliche Konversationen nutzt.

## Features

- **🔊 Offline Wakeword-Erkennung**: Aktivierung durch "Computer" (Picovoice Porcupine)
- **🗣️ Native Audio**: Direkte Audio-Kommunikation mit Gemini - kein separates STT/TTS nötig
- **📅 Google Kalender Integration**: Termine erstellen, anzeigen, bearbeiten und löschen
- **⏱️ Konversationsmodus**: Bleibt nach Aktivierung für Follow-up-Fragen aktiv
- **🍓 Raspberry Pi kompatibel**: Optimiert für Pi 4 mit USB-Audio

## Voraussetzungen

### Hardware
- Raspberry Pi 4 (oder Windows/Linux PC für Entwicklung)
- USB-Mikrofon
- USB-Soundkarte + Lautsprecher (oder USB-Lautsprecher)

### Software
- Python 3.10+
- PortAudio (für PyAudio)

## Installation

### 1. Repository klonen

```bash
git clone <your-repo-url>
cd voice-assistant
```

### 2. Virtuelle Umgebung erstellen

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Linux/Mac/Pi
source venv/bin/activate
```

### 3. Abhängigkeiten installieren

**Windows:**
```bash
pip install -r requirements.txt
```

**Raspberry Pi / Linux:**
```bash
# PortAudio installieren (für PyAudio)
sudo apt-get update
sudo apt-get install -y portaudio19-dev python3-pyaudio

pip install -r requirements.txt
```

### 4. Konfiguration

```bash
# .env Datei erstellen
cp .env.example .env
```

Bearbeite `.env` und füge deine API-Keys ein:

```env
PORCUPINE_ACCESS_KEY=dein_porcupine_key
GEMINI_API_KEY=dein_gemini_key
```

### 5. API-Keys besorgen

#### Picovoice Porcupine (Wakeword)
1. Registriere dich bei [Picovoice Console](https://console.picovoice.ai/)
2. Kopiere deinen Access Key

#### Google Gemini API
1. Gehe zu [Google AI Studio](https://aistudio.google.com/app/apikey)
2. Erstelle einen neuen API Key

#### Google Calendar (optional)
1. Gehe zur [Google Cloud Console](https://console.cloud.google.com/)
2. Erstelle ein neues Projekt
3. Aktiviere die Google Calendar API
4. Erstelle OAuth 2.0 Credentials (Desktop App)
5. Lade `credentials.json` herunter und lege sie ins Projektverzeichnis

### 6. Sound-Dateien generieren

```bash
python scripts/generate_sounds.py
```

## Verwendung

### Assistent starten

```bash
python main.py
```

### Audio-Geräte auflisten

```bash
python main.py --list-devices
```

### Audio testen

```bash
python main.py --test-audio
```

### Wakeword testen

```bash
python main.py --test-wakeword
```

## Sprachbefehle (Beispiele)

Nach Aktivierung mit "Computer":

### Kalender
- "Was habe ich heute vor?"
- "Welche Termine habe ich morgen?"
- "Erstelle einen Termin für Montag um 14 Uhr - Zahnarzt"
- "Lösche den Zahnarzt-Termin"
- "Verschiebe den Meeting-Termin auf 15 Uhr"

### Allgemein
- "Wie spät ist es?"
- "Wie ist das Wetter?" (benötigt zusätzliches Tool)
- Beliebige Konversation...

## Projektstruktur

```
voice-assistant/
├── main.py                 # Haupteinstiegspunkt
├── requirements.txt        # Python-Abhängigkeiten
├── .env.example           # Beispiel-Konfiguration
├── credentials.json       # Google OAuth Credentials (nicht im Repo)
├── token.json            # Google OAuth Token (generiert)
├── sounds/
│   ├── activation.wav    # Aktivierungston
│   └── deactivation.wav  # Deaktivierungston
├── scripts/
│   └── generate_sounds.py # Sound-Generator
└── src/
    ├── __init__.py
    ├── config.py          # Konfiguration
    ├── assistant.py       # Haupt-Orchestrator
    ├── audio/
    │   ├── __init__.py
    │   ├── handler.py     # Mikrofon-Eingabe
    │   └── player.py      # Audio-Ausgabe
    ├── wakeword/
    │   ├── __init__.py
    │   └── detector.py    # Porcupine Wakeword
    ├── gemini/
    │   ├── __init__.py
    │   └── client.py      # Gemini Live API
    └── tools/
        ├── __init__.py
        └── calendar.py    # Google Calendar Tool
```

## Raspberry Pi Setup

### Audio-Konfiguration

1. USB-Geräte prüfen:
```bash
arecord -l  # Mikrofone
aplay -l    # Lautsprecher
```

2. Standard-Geräte setzen in `/etc/asound.conf`:
```
defaults.pcm.card 1
defaults.ctl.card 1
```

3. Audio testen:
```bash
# Aufnahme testen
arecord -d 3 -f S16_LE -r 16000 test.wav

# Wiedergabe testen
aplay test.wav
```

### Autostart (systemd)

Erstelle `/etc/systemd/system/voice-assistant.service`:

```ini
[Unit]
Description=Voice Assistant
After=network.target sound.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/voice-assistant
ExecStart=/home/pi/voice-assistant/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Aktivieren:
```bash
sudo systemctl enable voice-assistant
sudo systemctl start voice-assistant
```

## Erweiterung mit neuen Tools

Neue Tools können einfach hinzugefügt werden:

1. Erstelle eine neue Tool-Klasse in `src/tools/`
2. Definiere `TOOL_DEFINITIONS` mit JSON Schema
3. Implementiere Handler-Methoden
4. Registriere in `src/assistant.py`

Beispiel:
```python
# src/tools/weather.py
class WeatherTool:
    TOOL_DEFINITIONS = [{
        "name": "get_weather",
        "description": "Holt das aktuelle Wetter",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {"type": "string"}
            }
        }
    }]
    
    async def get_weather(self, city: str) -> dict:
        # Implementierung...
        pass
```

## Troubleshooting

### "Porcupine access key invalid"
- Prüfe ob der Key korrekt in `.env` eingetragen ist
- Erstelle ggf. einen neuen Key in der Picovoice Console

### Kein Audio-Input
- `python main.py --list-devices` ausführen
- Gerätename in `.env` als `AUDIO_INPUT_DEVICE` setzen
- Unter Linux: `pulseaudio --start` oder ALSA konfigurieren

### Google Calendar Authentifizierung schlägt fehl
- Stelle sicher dass `credentials.json` im Projektverzeichnis liegt
- Lösche `token.json` und authentifiziere neu

### Hohe Latenz
- Prüfe Internetverbindung
- Reduziere `chunk_size` in config (kann CPU-Last erhöhen)

## Lizenz

MIT License

## Beitragen

Pull Requests sind willkommen! Für größere Änderungen bitte erst ein Issue erstellen.
