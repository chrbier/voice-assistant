"""
Music Tool for YouTube audio playback.
Uses yt-dlp to stream audio from YouTube headlessly.
"""

import logging
import subprocess
import threading
import os
import signal
import psutil
from typing import Optional, Callable, List

logger = logging.getLogger(__name__)


class MusicTool:
    """
    Music playback via YouTube using yt-dlp.
    Streams audio headlessly without downloading.
    Supports playlists with automatic next song playback.
    """
    
    def __init__(self):
        self._process: Optional[subprocess.Popen] = None
        self._is_playing = False
        self._current_title: Optional[str] = None
        self._volume = 100  # 0-100
        self._player = "mpv"  # or "ffplay"
        self._player_pids: List[int] = []  # Track all player PIDs
        
        # Playlist support
        self._playlist: List[dict] = []  # Queue of songs [{id, title}, ...]
        self._playlist_index = 0
        self._playlist_name: Optional[str] = None
        self._auto_next = True  # Auto-play next song
        self._monitor_thread: Optional[threading.Thread] = None
    
    def initialize(self) -> None:
        """Check if required tools are installed."""
        # Check for yt-dlp
        try:
            result = subprocess.run(
                ["yt-dlp", "--version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            logger.info(f"✓ yt-dlp verfügbar: {result.stdout.strip()}")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            raise RuntimeError("yt-dlp nicht installiert. Installiere mit: pip install yt-dlp")
        
        # Check for audio player (mpv preferred, ffplay as fallback)
        for player in ["mpv", "ffplay"]:
            try:
                subprocess.run(
                    [player, "--version"] if player == "mpv" else [player, "-version"],
                    capture_output=True,
                    timeout=5
                )
                self._player = player
                logger.info(f"✓ Audio-Player: {player}")
                return
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue
        
        raise RuntimeError("Kein Audio-Player gefunden. Installiere mpv oder ffmpeg.")
    
    def _search_youtube(self, query: str) -> Optional[dict]:
        """Search YouTube and get best audio URL with improved matching."""
        import json
        
        # Enhance search query for better music results
        search_query = f"{query} official audio"
        
        try:
            # Get multiple results as JSON for better selection
            result = subprocess.run(
                [
                    "yt-dlp",
                    f"ytsearch5:{search_query}",  # Get 5 results
                    "--dump-json",
                    "--flat-playlist",
                    "--no-warnings",
                    "--quiet"
                ],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0:
                logger.error(f"yt-dlp Suche Fehler: {result.stderr}")
                # Fallback to simple search
                return self._simple_youtube_search(query)
            
            # Parse JSON results
            videos = []
            for line in result.stdout.strip().split('\n'):
                if line:
                    try:
                        video = json.loads(line)
                        videos.append(video)
                    except json.JSONDecodeError:
                        continue
            
            if not videos:
                # Fallback to simple search without "official audio"
                return self._simple_youtube_search(query)
            
            # Score and rank results
            query_lower = query.lower()
            query_words = set(query_lower.split())
            
            best_video = None
            best_score = -1
            
            for video in videos:
                title = video.get('title', '').lower()
                channel = video.get('channel', '').lower()
                duration = video.get('duration', 0) or 0
                view_count = video.get('view_count', 0) or 0
                
                score = 0
                
                # Title word matching
                title_words = set(title.split())
                matching_words = query_words & title_words
                score += len(matching_words) * 20
                
                # Exact query in title
                if query_lower in title:
                    score += 50
                
                # Prefer official/audio versions
                if 'official' in title:
                    score += 15
                if 'audio' in title:
                    score += 10
                if 'lyrics' in title:
                    score += 5
                if 'music video' in title:
                    score += 5
                
                # Penalize covers, remixes, live versions (unless requested)
                if 'cover' in title and 'cover' not in query_lower:
                    score -= 30
                if 'remix' in title and 'remix' not in query_lower:
                    score -= 20
                if 'live' in title and 'live' not in query_lower:
                    score -= 10
                if 'karaoke' in title:
                    score -= 40
                if '8d audio' in title:
                    score -= 20
                if 'slowed' in title or 'reverb' in title:
                    score -= 25
                
                # Prefer reasonable song lengths (2-8 minutes)
                if 120 <= duration <= 480:
                    score += 10
                elif duration > 600:  # Penalize very long videos
                    score -= 15
                
                # Slight boost for popular videos
                if view_count > 1000000:
                    score += 5
                if view_count > 10000000:
                    score += 5
                
                logger.debug(f"Video: '{video.get('title')}' Score: {score}")
                
                if score > best_score:
                    best_score = score
                    best_video = video
            
            if best_video:
                video_id = best_video.get('id')
                title = best_video.get('title')
                
                logger.info(f"🎵 Beste Übereinstimmung: '{title}' (Score: {best_score})")
                
                # Now get the actual audio URL
                return self._get_audio_url(video_id, title)
            
            return None
            
        except subprocess.TimeoutExpired:
            logger.error("YouTube-Suche Timeout")
            return self._simple_youtube_search(query)
        except Exception as e:
            logger.error(f"YouTube-Suche Fehler: {e}")
            return self._simple_youtube_search(query)
    
    def _simple_youtube_search(self, query: str) -> Optional[dict]:
        """Simple fallback YouTube search."""
        try:
            result = subprocess.run(
                [
                    "yt-dlp",
                    f"ytsearch1:{query}",
                    "--get-url",
                    "--get-title",
                    "-f", "bestaudio/best",
                    "--no-playlist",
                    "--no-warnings"
                ],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0:
                return None
            
            lines = result.stdout.strip().split('\n')
            if len(lines) >= 2:
                return {
                    "title": lines[0],
                    "url": lines[1]
                }
            return None
        except:
            return None
    
    def _get_audio_url(self, video_id: str, title: str) -> Optional[dict]:
        """Get audio URL for a specific video ID."""
        try:
            result = subprocess.run(
                [
                    "yt-dlp",
                    f"https://www.youtube.com/watch?v={video_id}",
                    "--get-url",
                    "-f", "bestaudio/best",
                    "--no-playlist",
                    "--no-warnings"
                ],
                capture_output=True,
                text=True,
                timeout=20
            )
            
            if result.returncode == 0 and result.stdout.strip():
                return {
                    "title": title,
                    "url": result.stdout.strip().split('\n')[0]
                }
            return None
        except:
            return None
    
    def _play_audio_url(self, url: str, title: str) -> bool:
        """Play audio URL using mpv or ffplay."""
        try:
            # Stop any current playback and kill ALL player processes
            self._kill_all_players()
            self._process = None
            self._is_playing = False
            
            if self._player == "mpv":
                cmd = [
                    "mpv",
                    "--no-video",
                    "--really-quiet",
                    f"--volume={self._volume}",
                    url
                ]
            else:  # ffplay
                cmd = [
                    "ffplay",
                    "-nodisp",
                    "-autoexit",
                    "-loglevel", "quiet",
                    "-volume", str(self._volume),
                    url
                ]
            
            # Start playback in background
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            
            self._is_playing = True
            self._current_title = title
            logger.info(f"▶ Spiele: {title}")
            
            # Monitor process and auto-play next song
            def monitor():
                if self._process:
                    self._process.wait()
                    self._is_playing = False
                    logger.debug("Wiedergabe beendet")
                    
                    # Auto-play next song in playlist
                    if self._auto_next and self._playlist and self._playlist_index < len(self._playlist) - 1:
                        self._playlist_index += 1
                        self._play_next_in_playlist()
                    else:
                        self._current_title = None
            
            self._monitor_thread = threading.Thread(target=monitor, daemon=True)
            self._monitor_thread.start()
            return True
            
        except Exception as e:
            logger.error(f"Wiedergabe-Fehler: {e}")
            return False
    
    # === Tool Functions for Gemini ===
    
    def play_music(self, query: str) -> str:
        """
        Search and play music from YouTube.
        
        Args:
            query: Song name, artist, or search query
            
        Returns:
            Status message
        """
        logger.info(f"🎵 Suche Musik: '{query}'...")
        
        result = self._search_youtube(query)
        if not result:
            return f"Konnte '{query}' nicht auf YouTube finden."
        
        # Clear playlist when playing single song
        self._playlist = []
        self._playlist_index = 0
        self._playlist_name = None
        
        if self._play_audio_url(result["url"], result["title"]):
            return f"Spiele jetzt: {result['title']}"
        else:
            return "Fehler beim Abspielen der Musik."
    
    def play_playlist(self, artist_or_query: str, count: int = 10) -> str:
        """
        Create and play a playlist of songs from an artist or search query.
        
        Args:
            artist_or_query: Artist name or search query (e.g., "Larkin Poe", "80s Rock")
            count: Number of songs to add (default 10, max 20)
            
        Returns:
            Status message
        """
        import json
        
        count = min(max(3, count), 20)  # Limit 3-20 songs
        logger.info(f"🎵 Erstelle Playlist: '{artist_or_query}' ({count} Songs)...")
        
        search_query = f"{artist_or_query} songs"
        
        try:
            # Search for multiple videos
            result = subprocess.run(
                [
                    "yt-dlp",
                    f"ytsearch{count + 5}:{search_query}",  # Get extra for filtering
                    "--dump-json",
                    "--flat-playlist",
                    "--no-warnings",
                    "--quiet"
                ],
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode != 0:
                return f"Konnte keine Songs für '{artist_or_query}' finden."
            
            # Parse results
            videos = []
            for line in result.stdout.strip().split('\n'):
                if line:
                    try:
                        video = json.loads(line)
                        videos.append(video)
                    except json.JSONDecodeError:
                        continue
            
            if not videos:
                return f"Keine Songs für '{artist_or_query}' gefunden."
            
            # Filter and score videos
            query_lower = artist_or_query.lower()
            scored_videos = []
            
            for video in videos:
                title = video.get('title', '').lower()
                duration = video.get('duration', 0) or 0
                
                # Skip non-music content
                if 'interview' in title or 'behind the scenes' in title:
                    continue
                if 'karaoke' in title or 'instrumental' in title:
                    continue
                if duration < 90 or duration > 600:  # Skip <1.5min or >10min
                    continue
                
                score = 0
                
                # Artist name in title
                if query_lower in title:
                    score += 30
                
                # Prefer official content
                if 'official' in title:
                    score += 10
                if 'audio' in title or 'video' in title:
                    score += 5
                
                # Penalize covers/remixes
                if 'cover' in title:
                    score -= 20
                if 'remix' in title:
                    score -= 15
                if 'live' in title:
                    score -= 5
                
                scored_videos.append((score, video))
            
            # Sort by score and take top N
            scored_videos.sort(key=lambda x: x[0], reverse=True)
            selected = [v for _, v in scored_videos[:count]]
            
            if not selected:
                return f"Keine passenden Songs für '{artist_or_query}' gefunden."
            
            # Build playlist
            self._playlist = [
                {"id": v.get('id'), "title": v.get('title')}
                for v in selected
            ]
            self._playlist_index = 0
            self._playlist_name = artist_or_query
            
            # Start playing first song
            song_titles = [s['title'] for s in self._playlist[:5]]
            titles_preview = ", ".join(song_titles)
            if len(self._playlist) > 5:
                titles_preview += f" ... und {len(self._playlist) - 5} weitere"
            
            logger.info(f"📋 Playlist erstellt: {len(self._playlist)} Songs")
            
            # Play first song
            self._play_next_in_playlist()
            
            return f"Playlist '{artist_or_query}' mit {len(self._playlist)} Songs erstellt. Spiele: {self._playlist[0]['title']}"
            
        except subprocess.TimeoutExpired:
            return "Timeout bei der Playlist-Suche."
        except Exception as e:
            logger.error(f"Playlist-Fehler: {e}")
            return f"Fehler beim Erstellen der Playlist: {e}"
    
    def _play_next_in_playlist(self) -> bool:
        """Play current song in playlist."""
        if not self._playlist or self._playlist_index >= len(self._playlist):
            return False
        
        song = self._playlist[self._playlist_index]
        video_id = song.get('id')
        title = song.get('title')
        
        logger.info(f"📋 Playlist [{self._playlist_index + 1}/{len(self._playlist)}]: {title}")
        
        # Get audio URL and play
        result = self._get_audio_url(video_id, title)
        if result:
            return self._play_audio_url(result['url'], result['title'])
        return False
    
    def skip_song(self) -> str:
        """
        Skip to next song in playlist.
        
        Returns:
            Status message
        """
        if not self._playlist:
            return "Keine Playlist aktiv."
        
        if self._playlist_index >= len(self._playlist) - 1:
            return "Das war der letzte Song in der Playlist."
        
        # Stop current and play next
        self._kill_all_players()
        self._playlist_index += 1
        
        if self._play_next_in_playlist():
            return f"Überspringe zu: {self._playlist[self._playlist_index]['title']}"
        else:
            return "Fehler beim Überspringen."
    
    def previous_song(self) -> str:
        """
        Go back to previous song in playlist.
        
        Returns:
            Status message
        """
        if not self._playlist:
            return "Keine Playlist aktiv."
        
        if self._playlist_index <= 0:
            return "Das ist bereits der erste Song."
        
        # Stop current and play previous
        self._kill_all_players()
        self._playlist_index -= 1
        
        if self._play_next_in_playlist():
            return f"Zurück zu: {self._playlist[self._playlist_index]['title']}"
        else:
            return "Fehler beim Zurückspringen."
    
    def _kill_all_players(self) -> int:
        """Kill all mpv/ffplay processes. Returns count of killed processes."""
        killed = 0
        player_names = ["mpv", "mpv.exe", "ffplay", "ffplay.exe"]
        
        try:
            for proc in psutil.process_iter(['pid', 'name']):
                try:
                    if proc.info['name'] and proc.info['name'].lower() in [p.lower() for p in player_names]:
                        proc.kill()
                        killed += 1
                        logger.debug(f"Killed player process: {proc.info['name']} (PID {proc.info['pid']})")
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except Exception as e:
            logger.error(f"Fehler beim Beenden der Player: {e}")
        
        return killed
    
    def stop(self) -> str:
        """
        Stop current music playback.
        
        Returns:
            Status message
        """
        # First try to stop our tracked process
        if self._process:
            try:
                if os.name == 'nt':
                    self._process.terminate()
                else:
                    self._process.send_signal(signal.SIGTERM)
                self._process.wait(timeout=2)
            except:
                try:
                    self._process.kill()
                except:
                    pass
            finally:
                self._process = None
        
        # Also kill any orphaned player processes
        killed = self._kill_all_players()
        
        was_playing = self._is_playing
        self._is_playing = False
        title = self._current_title
        self._current_title = None
        
        # Clear playlist
        playlist_name = self._playlist_name
        self._playlist = []
        self._playlist_index = 0
        self._playlist_name = None
        
        if was_playing or killed > 0:
            logger.info(f"⏹ Musik gestoppt (beendete Prozesse: {killed})")
            if playlist_name:
                return f"Playlist '{playlist_name}' gestoppt."
            return f"Musik gestoppt: {title}" if title else "Musik gestoppt."
        return "Es läuft gerade keine Musik."
    
    def pause(self) -> str:
        """
        Pause music (only works with mpv).
        
        Returns:
            Status message
        """
        # Note: Pause/Resume requires IPC which is complex
        # For simplicity, we just stop
        return self.stop()
    
    def set_volume(self, volume: int) -> str:
        """
        Set playback volume.
        
        Args:
            volume: Volume level 0-100
            
        Returns:
            Status message
        """
        self._volume = max(0, min(100, volume))
        logger.info(f"🔊 Lautstärke: {self._volume}%")
        
        # Volume change takes effect on next playback
        # (changing during playback requires IPC)
        return f"Lautstärke auf {self._volume}% gesetzt. Gilt ab dem nächsten Lied."
    
    def get_status(self) -> str:
        """
        Get current playback status.
        
        Returns:
            Status message
        """
        if self._is_playing and self._current_title:
            if self._playlist:
                return f"Spielt: {self._current_title} (Song {self._playlist_index + 1} von {len(self._playlist)} in Playlist '{self._playlist_name}')"
            return f"Spielt gerade: {self._current_title}"
        return "Es läuft gerade keine Musik."
    
    def get_tool_definitions(self) -> list[dict]:
        """Return tool definitions for Gemini."""
        return [
            {
                "name": "play_music",
                "description": "Sucht und spielt Musik von YouTube ab. Beispiel: 'Spiele Bohemian Rhapsody' oder 'Spiele Musik von Mozart'",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Suchbegriff: Songname, Künstler oder beides"
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "stop_music",
                "description": "Stoppt die aktuelle Musikwiedergabe. Beispiel: 'Stoppe die Musik'",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "music_volume",
                "description": "Setzt die Musiklautstärke (0-100). Beispiel: 'Mach die Musik leiser' oder 'Lautstärke auf 50%'",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "volume": {
                            "type": "integer",
                            "description": "Lautstärke in Prozent (0-100)"
                        }
                    },
                    "required": ["volume"]
                }
            },
            {
                "name": "music_status",
                "description": "Zeigt an was gerade gespielt wird. Beispiel: 'Was läuft gerade?'",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "play_playlist",
                "description": "Erstellt und spielt eine Playlist mit mehreren Songs eines Künstlers. Beispiel: 'Spiele Lieder von Larkin Poe' oder 'Mach eine Playlist mit 80er Rock'",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "artist_or_query": {
                            "type": "string",
                            "description": "Künstlername oder Suchbegriff für die Playlist"
                        },
                        "count": {
                            "type": "integer",
                            "description": "Anzahl der Songs (Standard: 10, Maximum: 20)"
                        }
                    },
                    "required": ["artist_or_query"]
                }
            },
            {
                "name": "skip_song",
                "description": "Springt zum nächsten Song in der Playlist. Beispiel: 'Nächster Song' oder 'Überspringe dieses Lied'",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "previous_song",
                "description": "Springt zum vorherigen Song in der Playlist. Beispiel: 'Vorheriger Song' oder 'Zurück'",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            }
        ]
    
    def get_tool_handlers(self) -> dict[str, Callable]:
        """Return mapping of tool names to handler functions."""
        return {
            "play_music": self.play_music,
            "stop_music": self.stop,
            "music_volume": self.set_volume,
            "music_status": self.get_status,
            "play_playlist": self.play_playlist,
            "skip_song": self.skip_song,
            "previous_song": self.previous_song,
        }
    
    def cleanup(self) -> None:
        """Clean up resources."""
        self.stop()
