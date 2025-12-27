"""
News Tool using RSS feeds.
Provides current news headlines from German news sources.
"""

import logging
import urllib.request
import xml.etree.ElementTree as ET
from typing import Optional, Callable, List, Dict
from datetime import datetime
import html
import re

logger = logging.getLogger(__name__)


# German news RSS feeds
NEWS_SOURCES = {
    "tagesschau": {
        "name": "Tagesschau",
        "url": "https://www.tagesschau.de/index~rss2.xml",
        "category": "allgemein"
    },
    "spiegel": {
        "name": "Spiegel",
        "url": "https://www.spiegel.de/schlagzeilen/tops/index.rss",
        "category": "allgemein"
    },
    "zeit": {
        "name": "Zeit Online",
        "url": "https://newsfeed.zeit.de/index",
        "category": "allgemein"
    },
    "heise": {
        "name": "Heise",
        "url": "https://www.heise.de/rss/heise-atom.xml",
        "category": "technik"
    },
    "sportschau": {
        "name": "Sportschau",
        "url": "https://www.sportschau.de/index~rss2.xml",
        "category": "sport"
    },
    "tagesschau_wirtschaft": {
        "name": "Tagesschau Wirtschaft",
        "url": "https://www.tagesschau.de/wirtschaft/index~rss2.xml",
        "category": "wirtschaft"
    }
}


class NewsTool:
    """
    News headlines from German RSS feeds.
    Supports multiple sources and categories.
    """
    
    def __init__(self):
        self._default_source = "tagesschau"
        self._cache: Dict[str, tuple] = {}  # source -> (timestamp, items)
        self._cache_duration = 300  # 5 minutes
    
    def initialize(self) -> None:
        """Initialize news tool."""
        logger.info(f"✓ Nachrichten-Tool initialisiert ({len(NEWS_SOURCES)} Quellen)")
    
    def _clean_text(self, text: str) -> str:
        """Clean HTML entities and extra whitespace from text."""
        if not text:
            return ""
        # Decode HTML entities
        text = html.unescape(text)
        # Remove HTML tags
        text = re.sub(r'<[^>]+>', '', text)
        # Clean whitespace
        text = ' '.join(text.split())
        return text.strip()
    
    def _parse_rss(self, xml_content: str) -> List[Dict]:
        """Parse RSS/Atom feed and extract items."""
        items = []
        
        try:
            root = ET.fromstring(xml_content)
            
            # Handle RSS 2.0
            for item in root.findall('.//item'):
                title = item.find('title')
                description = item.find('description')
                pub_date = item.find('pubDate')
                
                if title is not None and title.text:
                    items.append({
                        "title": self._clean_text(title.text),
                        "description": self._clean_text(description.text) if description is not None else "",
                        "date": pub_date.text if pub_date is not None else ""
                    })
            
            # Handle Atom feeds
            if not items:
                ns = {'atom': 'http://www.w3.org/2005/Atom'}
                for entry in root.findall('.//atom:entry', ns) or root.findall('.//entry'):
                    title = entry.find('atom:title', ns) or entry.find('title')
                    summary = entry.find('atom:summary', ns) or entry.find('summary')
                    updated = entry.find('atom:updated', ns) or entry.find('updated')
                    
                    if title is not None and title.text:
                        items.append({
                            "title": self._clean_text(title.text),
                            "description": self._clean_text(summary.text) if summary is not None else "",
                            "date": updated.text if updated is not None else ""
                        })
            
        except ET.ParseError as e:
            logger.error(f"RSS Parse-Fehler: {e}")
        
        return items
    
    def _fetch_feed(self, source_key: str) -> List[Dict]:
        """Fetch and parse RSS feed with caching."""
        if source_key not in NEWS_SOURCES:
            return []
        
        # Check cache
        if source_key in self._cache:
            timestamp, items = self._cache[source_key]
            if (datetime.now().timestamp() - timestamp) < self._cache_duration:
                return items
        
        source = NEWS_SOURCES[source_key]
        url = source["url"]
        
        try:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": "VoiceAssistant/1.0"}
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                content = response.read().decode('utf-8')
                items = self._parse_rss(content)
                
                # Cache results
                self._cache[source_key] = (datetime.now().timestamp(), items)
                
                return items
                
        except Exception as e:
            logger.error(f"Fehler beim Abrufen von {source['name']}: {e}")
            return []
    
    def _format_headlines(self, items: List[Dict], count: int, source_name: str) -> str:
        """Format news items as readable text."""
        if not items:
            return f"Keine Nachrichten von {source_name} verfügbar."
        
        headlines = items[:count]
        
        result = f"Aktuelle Nachrichten von {source_name}: "
        
        news_texts = []
        for i, item in enumerate(headlines, 1):
            news_texts.append(f"{i}. {item['title']}")
        
        return result + " ".join(news_texts)
    
    # === Tool Functions for Gemini ===
    
    def get_news(self, source: str = "", count: int = 5) -> str:
        """
        Get current news headlines.
        
        Args:
            source: News source (tagesschau, spiegel, zeit, heise, sportschau)
            count: Number of headlines (1-10)
            
        Returns:
            News headlines
        """
        count = max(1, min(10, count))
        
        # Determine source
        source_key = source.lower().strip() if source else self._default_source
        
        # Handle category requests
        if source_key in ["sport", "sports"]:
            source_key = "sportschau"
        elif source_key in ["technik", "tech", "technology"]:
            source_key = "heise"
        elif source_key in ["wirtschaft", "economy", "business"]:
            source_key = "tagesschau_wirtschaft"
        elif source_key not in NEWS_SOURCES:
            # Try partial match
            for key in NEWS_SOURCES:
                if source_key in key or source_key in NEWS_SOURCES[key]["name"].lower():
                    source_key = key
                    break
            else:
                source_key = self._default_source
        
        source_info = NEWS_SOURCES.get(source_key, NEWS_SOURCES[self._default_source])
        logger.info(f"📰 Nachrichten-Abfrage: {source_info['name']} ({count} Artikel)")
        
        items = self._fetch_feed(source_key)
        
        return self._format_headlines(items, count, source_info["name"])
    
    def get_news_summary(self, topic: str = "") -> str:
        """
        Get news summary, optionally filtered by topic.
        
        Args:
            topic: Optional topic to filter news
            
        Returns:
            News summary
        """
        logger.info(f"📰 Nachrichten-Zusammenfassung" + (f" zu '{topic}'" if topic else ""))
        
        # Get news from main source
        items = self._fetch_feed(self._default_source)
        
        if topic:
            topic_lower = topic.lower()
            items = [
                item for item in items
                if topic_lower in item["title"].lower() or topic_lower in item["description"].lower()
            ]
        
        if not items:
            if topic:
                return f"Keine aktuellen Nachrichten zu '{topic}' gefunden."
            return "Keine Nachrichten verfügbar."
        
        # Take top 3 with descriptions
        result_parts = []
        for item in items[:3]:
            text = item["title"]
            if item["description"] and len(item["description"]) > 20:
                # Add short description
                desc = item["description"][:150]
                if len(item["description"]) > 150:
                    desc = desc.rsplit(' ', 1)[0] + "..."
                text += f": {desc}"
            result_parts.append(text)
        
        return "Aktuelle Nachrichten: " + " | ".join(result_parts)
    
    def list_sources(self) -> str:
        """
        List available news sources.
        
        Returns:
            List of sources
        """
        sources = []
        for key, info in NEWS_SOURCES.items():
            sources.append(f"{info['name']} ({info['category']})")
        
        return "Verfügbare Nachrichtenquellen: " + ", ".join(sources)
    
    def get_tool_definitions(self) -> list[dict]:
        """Return tool definitions for Gemini."""
        return [
            {
                "name": "get_news",
                "description": "Ruft aktuelle Nachrichten-Schlagzeilen ab. Quellen: Tagesschau, Spiegel, Zeit, Heise (Technik), Sportschau. Beispiel: 'Was sind die Nachrichten heute?' oder 'Sportnachrichten'",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "source": {
                            "type": "string",
                            "description": "Nachrichtenquelle: tagesschau, spiegel, zeit, heise, sportschau, wirtschaft (optional)"
                        },
                        "count": {
                            "type": "integer",
                            "description": "Anzahl der Schlagzeilen (1-10, Standard: 5)"
                        }
                    }
                }
            },
            {
                "name": "get_news_topic",
                "description": "Sucht Nachrichten zu einem bestimmten Thema. Beispiel: 'Gibt es Nachrichten über die Bundesliga?' oder 'News zu Elektroautos'",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "topic": {
                            "type": "string",
                            "description": "Thema für die Nachrichtensuche"
                        }
                    },
                    "required": ["topic"]
                }
            }
        ]
    
    def get_tool_handlers(self) -> dict[str, Callable]:
        """Return mapping of tool names to handler functions."""
        return {
            "get_news": self.get_news,
            "get_news_topic": self.get_news_summary,
        }
    
    def cleanup(self) -> None:
        """Clean up resources."""
        self._cache.clear()
