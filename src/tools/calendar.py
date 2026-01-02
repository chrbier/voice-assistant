"""
Google Calendar Tool for the voice assistant.
Provides functions to create, read, update, and delete calendar events.
"""

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Any
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from src.config import config

logger = logging.getLogger(__name__)


class GoogleCalendarTool:
    """
    Google Calendar integration for voice assistant.
    Supports multiple calendars (personal + shared).
    """
    
    # Tool definitions for Gemini function calling
    TOOL_DEFINITIONS = [
        {
            "name": "get_upcoming_events",
            "description": "Holt die nächsten Termine aus dem Kalender. Nutze dies wenn der Benutzer nach seinen Terminen fragt.",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": "Anzahl der Tage in die Zukunft (Standard: 7)"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximale Anzahl der Termine (Standard: 10)"
                    }
                },
                "required": []
            }
        },
        {
            "name": "get_events_on_date",
            "description": "Holt alle Termine für ein bestimmtes Datum. Nutze dies wenn der Benutzer nach Terminen an einem bestimmten Tag fragt.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "Das Datum im Format YYYY-MM-DD"
                    }
                },
                "required": ["date"]
            }
        },
        {
            "name": "create_event",
            "description": "Erstellt einen neuen Termin im Kalender. Nutze dies wenn der Benutzer einen Termin anlegen möchte.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Titel des Termins"
                    },
                    "start_datetime": {
                        "type": "string",
                        "description": "Startzeit im Format YYYY-MM-DDTHH:MM:SS"
                    },
                    "end_datetime": {
                        "type": "string",
                        "description": "Endzeit im Format YYYY-MM-DDTHH:MM:SS (optional, Standard: 1 Stunde nach Start)"
                    },
                    "description": {
                        "type": "string",
                        "description": "Beschreibung des Termins (optional)"
                    },
                    "location": {
                        "type": "string",
                        "description": "Ort des Termins (optional)"
                    }
                },
                "required": ["title", "start_datetime"]
            }
        },
        {
            "name": "update_event",
            "description": "Aktualisiert einen bestehenden Termin. Nutze dies wenn der Benutzer einen Termin ändern möchte.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {
                        "type": "string",
                        "description": "Die ID des zu ändernden Termins"
                    },
                    "title": {
                        "type": "string",
                        "description": "Neuer Titel (optional)"
                    },
                    "start_datetime": {
                        "type": "string",
                        "description": "Neue Startzeit im Format YYYY-MM-DDTHH:MM:SS (optional)"
                    },
                    "end_datetime": {
                        "type": "string",
                        "description": "Neue Endzeit im Format YYYY-MM-DDTHH:MM:SS (optional)"
                    },
                    "description": {
                        "type": "string",
                        "description": "Neue Beschreibung (optional)"
                    },
                    "location": {
                        "type": "string",
                        "description": "Neuer Ort (optional)"
                    }
                },
                "required": ["event_id"]
            }
        },
        {
            "name": "delete_event",
            "description": "Löscht einen Termin aus dem Kalender. Nutze dies wenn der Benutzer einen Termin absagen oder löschen möchte.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {
                        "type": "string",
                        "description": "Die ID des zu löschenden Termins"
                    }
                },
                "required": ["event_id"]
            }
        },
        {
            "name": "search_events",
            "description": "Sucht nach Terminen mit einem bestimmten Suchbegriff. Nutze dies wenn der Benutzer nach einem bestimmten Termin sucht.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Suchbegriff"
                    },
                    "days": {
                        "type": "integer",
                        "description": "Anzahl der Tage zu durchsuchen (Standard: 30)"
                    }
                },
                "required": ["query"]
            }
        }
    ]
    
    def __init__(self):
        self._service = None
        self._credentials = None
        self._calendar_ids: list[str] = ["primary"]  # Default to primary calendar
    
    def initialize(self) -> None:
        """Initialize Google Calendar API connection."""
        self._credentials = self._get_credentials()
        self._service = build("calendar", "v3", credentials=self._credentials)
        logger.info("Google Calendar API initialisiert")
        
        # Optionally load additional calendar IDs
        self._load_calendar_ids()
    
    def _get_credentials(self) -> Credentials:
        """Get or refresh Google OAuth credentials."""
        creds = None
        token_path = Path(config.calendar.token_file)
        credentials_path = Path(config.calendar.credentials_file)
        
        # Load existing token
        if token_path.exists():
            creds = Credentials.from_authorized_user_file(
                str(token_path),
                config.calendar.scopes
            )
        
        # Refresh or get new credentials
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                logger.info("Aktualisiere Google-Token...")
                try:
                    creds.refresh(Request())
                except Exception as refresh_error:
                    logger.warning(f"Token-Refresh fehlgeschlagen: {refresh_error}")
                    # Delete invalid token and re-authenticate
                    if token_path.exists():
                        token_path.unlink()
                    creds = None
            
            if not creds:
                if not credentials_path.exists():
                    raise FileNotFoundError(
                        f"Google Credentials nicht gefunden: {credentials_path}\n"
                        "Bitte lade die credentials.json von der Google Cloud Console herunter."
                    )
                
                logger.info("Starte Google OAuth-Authentifizierung...")
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(credentials_path),
                    config.calendar.scopes
                )
                
                # Try local server first, fall back to console for headless systems
                try:
                    creds = flow.run_local_server(port=0)
                except Exception:
                    # Headless mode: show URL for manual authentication
                    logger.info("Kein Browser verfügbar - nutze Console-Authentifizierung")
                    print("\n" + "="*60)
                    print("GOOGLE CALENDAR AUTHENTIFIZIERUNG")
                    print("="*60)
                    print("Öffne diese URL in einem Browser (z.B. auf deinem PC/Handy):")
                    print()
                    auth_url, _ = flow.authorization_url(prompt='consent')
                    print(auth_url)
                    print()
                    print("Nach der Anmeldung wirst du zu einer Seite weitergeleitet.")
                    print("Kopiere den 'code' Parameter aus der URL und füge ihn hier ein:")
                    print("(Die URL sieht aus wie: http://localhost/?code=XXXXX&scope=...)")
                    print("="*60)
                    code = input("Authorization Code eingeben: ").strip()
                    flow.fetch_token(code=code)
                    creds = flow.credentials
            
            # Save token for future use
            with open(token_path, "w") as token_file:
                token_file.write(creds.to_json())
            logger.info(f"Token gespeichert: {token_path}")
        
        return creds
    
    def _load_calendar_ids(self) -> None:
        """Load all accessible calendar IDs."""
        try:
            calendars_result = self._service.calendarList().list().execute()
            calendars = calendars_result.get("items", [])
            
            self._calendar_ids = [cal["id"] for cal in calendars if cal.get("accessRole") in ["owner", "writer"]]
            
            logger.info(f"Gefundene Kalender: {len(self._calendar_ids)}")
            for cal in calendars:
                logger.debug(f"  - {cal.get('summary', 'Unbenannt')} ({cal.get('accessRole')})")
                
        except HttpError as e:
            logger.error(f"Fehler beim Laden der Kalender: {e}")
    
    def _format_event(self, event: dict) -> dict:
        """Format event for response."""
        start = event.get("start", {})
        end = event.get("end", {})
        
        # Handle all-day events vs timed events
        start_str = start.get("dateTime", start.get("date", ""))
        end_str = end.get("dateTime", end.get("date", ""))
        
        return {
            "id": event.get("id"),
            "title": event.get("summary", "Ohne Titel"),
            "start": start_str,
            "end": end_str,
            "location": event.get("location", ""),
            "description": event.get("description", ""),
            "calendar": event.get("organizer", {}).get("displayName", "Mein Kalender")
        }
    
    async def get_upcoming_events(self, days: int = 7, max_results: int = 10) -> dict:
        """Get upcoming events from all calendars."""
        try:
            now = datetime.utcnow()
            time_min = now.isoformat() + "Z"
            time_max = (now + timedelta(days=days)).isoformat() + "Z"
            
            all_events = []
            
            for calendar_id in self._calendar_ids:
                try:
                    events_result = self._service.events().list(
                        calendarId=calendar_id,
                        timeMin=time_min,
                        timeMax=time_max,
                        maxResults=max_results,
                        singleEvents=True,
                        orderBy="startTime"
                    ).execute()
                    
                    events = events_result.get("items", [])
                    all_events.extend([self._format_event(e) for e in events])
                    
                except HttpError as e:
                    logger.warning(f"Fehler bei Kalender {calendar_id}: {e}")
            
            # Sort by start time
            all_events.sort(key=lambda x: x["start"])
            
            return {
                "success": True,
                "count": len(all_events[:max_results]),
                "events": all_events[:max_results]
            }
            
        except Exception as e:
            logger.error(f"Fehler beim Abrufen der Termine: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_events_on_date(self, date: str) -> dict:
        """Get all events on a specific date."""
        try:
            # Parse date
            target_date = datetime.strptime(date, "%Y-%m-%d")
            time_min = target_date.isoformat() + "Z"
            time_max = (target_date + timedelta(days=1)).isoformat() + "Z"
            
            all_events = []
            
            for calendar_id in self._calendar_ids:
                try:
                    events_result = self._service.events().list(
                        calendarId=calendar_id,
                        timeMin=time_min,
                        timeMax=time_max,
                        singleEvents=True,
                        orderBy="startTime"
                    ).execute()
                    
                    events = events_result.get("items", [])
                    all_events.extend([self._format_event(e) for e in events])
                    
                except HttpError as e:
                    logger.warning(f"Fehler bei Kalender {calendar_id}: {e}")
            
            all_events.sort(key=lambda x: x["start"])
            
            return {
                "success": True,
                "date": date,
                "count": len(all_events),
                "events": all_events
            }
            
        except ValueError as e:
            return {"success": False, "error": f"Ungültiges Datumsformat: {date}"}
        except Exception as e:
            logger.error(f"Fehler beim Abrufen der Termine: {e}")
            return {"success": False, "error": str(e)}
    
    async def create_event(
        self,
        title: str,
        start_datetime: str,
        end_datetime: Optional[str] = None,
        description: Optional[str] = None,
        location: Optional[str] = None
    ) -> dict:
        """Create a new calendar event."""
        try:
            # Parse start time
            start_dt = datetime.fromisoformat(start_datetime)
            
            # Default end time: 1 hour after start
            if end_datetime:
                end_dt = datetime.fromisoformat(end_datetime)
            else:
                end_dt = start_dt + timedelta(hours=1)
            
            event_body = {
                "summary": title,
                "start": {
                    "dateTime": start_dt.isoformat(),
                    "timeZone": "Europe/Berlin"
                },
                "end": {
                    "dateTime": end_dt.isoformat(),
                    "timeZone": "Europe/Berlin"
                }
            }
            
            if description:
                event_body["description"] = description
            if location:
                event_body["location"] = location
            
            # Create on primary calendar
            event = self._service.events().insert(
                calendarId="primary",
                body=event_body
            ).execute()
            
            logger.info(f"Termin erstellt: {title} am {start_datetime}")
            
            return {
                "success": True,
                "message": f"Termin '{title}' wurde erstellt",
                "event": self._format_event(event)
            }
            
        except ValueError as e:
            return {"success": False, "error": f"Ungültiges Datum/Zeit-Format: {e}"}
        except HttpError as e:
            logger.error(f"API-Fehler beim Erstellen: {e}")
            return {"success": False, "error": str(e)}
        except Exception as e:
            logger.error(f"Fehler beim Erstellen des Termins: {e}")
            return {"success": False, "error": str(e)}
    
    async def update_event(
        self,
        event_id: str,
        title: Optional[str] = None,
        start_datetime: Optional[str] = None,
        end_datetime: Optional[str] = None,
        description: Optional[str] = None,
        location: Optional[str] = None
    ) -> dict:
        """Update an existing calendar event."""
        try:
            # Find the event
            event = None
            source_calendar = None
            
            for calendar_id in self._calendar_ids:
                try:
                    event = self._service.events().get(
                        calendarId=calendar_id,
                        eventId=event_id
                    ).execute()
                    source_calendar = calendar_id
                    break
                except HttpError:
                    continue
            
            if not event:
                return {"success": False, "error": f"Termin mit ID {event_id} nicht gefunden"}
            
            # Update fields
            if title:
                event["summary"] = title
            if start_datetime:
                event["start"] = {
                    "dateTime": datetime.fromisoformat(start_datetime).isoformat(),
                    "timeZone": "Europe/Berlin"
                }
            if end_datetime:
                event["end"] = {
                    "dateTime": datetime.fromisoformat(end_datetime).isoformat(),
                    "timeZone": "Europe/Berlin"
                }
            if description is not None:
                event["description"] = description
            if location is not None:
                event["location"] = location
            
            updated_event = self._service.events().update(
                calendarId=source_calendar,
                eventId=event_id,
                body=event
            ).execute()
            
            logger.info(f"Termin aktualisiert: {event_id}")
            
            return {
                "success": True,
                "message": "Termin wurde aktualisiert",
                "event": self._format_event(updated_event)
            }
            
        except HttpError as e:
            logger.error(f"API-Fehler beim Aktualisieren: {e}")
            return {"success": False, "error": str(e)}
        except Exception as e:
            logger.error(f"Fehler beim Aktualisieren: {e}")
            return {"success": False, "error": str(e)}
    
    async def delete_event(self, event_id: str) -> dict:
        """Delete a calendar event."""
        try:
            # Find and delete the event
            for calendar_id in self._calendar_ids:
                try:
                    # First get the event to confirm it exists
                    event = self._service.events().get(
                        calendarId=calendar_id,
                        eventId=event_id
                    ).execute()
                    
                    event_title = event.get("summary", "Ohne Titel")
                    
                    # Delete it
                    self._service.events().delete(
                        calendarId=calendar_id,
                        eventId=event_id
                    ).execute()
                    
                    logger.info(f"Termin gelöscht: {event_id}")
                    
                    return {
                        "success": True,
                        "message": f"Termin '{event_title}' wurde gelöscht"
                    }
                    
                except HttpError as e:
                    if e.resp.status != 404:
                        raise
                    continue
            
            return {"success": False, "error": f"Termin mit ID {event_id} nicht gefunden"}
            
        except HttpError as e:
            logger.error(f"API-Fehler beim Löschen: {e}")
            return {"success": False, "error": str(e)}
        except Exception as e:
            logger.error(f"Fehler beim Löschen: {e}")
            return {"success": False, "error": str(e)}
    
    async def search_events(self, query: str, days: int = 30) -> dict:
        """Search for events matching a query."""
        try:
            now = datetime.utcnow()
            time_min = now.isoformat() + "Z"
            time_max = (now + timedelta(days=days)).isoformat() + "Z"
            
            all_events = []
            
            for calendar_id in self._calendar_ids:
                try:
                    events_result = self._service.events().list(
                        calendarId=calendar_id,
                        timeMin=time_min,
                        timeMax=time_max,
                        q=query,
                        singleEvents=True,
                        orderBy="startTime"
                    ).execute()
                    
                    events = events_result.get("items", [])
                    all_events.extend([self._format_event(e) for e in events])
                    
                except HttpError as e:
                    logger.warning(f"Fehler bei Kalender {calendar_id}: {e}")
            
            all_events.sort(key=lambda x: x["start"])
            
            return {
                "success": True,
                "query": query,
                "count": len(all_events),
                "events": all_events
            }
            
        except Exception as e:
            logger.error(f"Fehler bei der Suche: {e}")
            return {"success": False, "error": str(e)}
    
    def get_tool_definitions(self) -> list[dict]:
        """Get tool definitions for Gemini registration."""
        return self.TOOL_DEFINITIONS
    
    def get_tool_handlers(self) -> dict:
        """Get mapping of tool names to handler methods."""
        return {
            "get_upcoming_events": self.get_upcoming_events,
            "get_events_on_date": self.get_events_on_date,
            "create_event": self.create_event,
            "update_event": self.update_event,
            "delete_event": self.delete_event,
            "search_events": self.search_events
        }
