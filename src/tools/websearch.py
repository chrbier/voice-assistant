"""
Web Search Tool using Tavily API.
Provides AI-optimized web search for current information.
"""

import logging
import os
import urllib.request
import urllib.parse
import json
from typing import Optional, Callable, Dict, Any, List

logger = logging.getLogger(__name__)


class WebSearchTool:
    """
    Web search using Tavily API.
    Optimized for AI agents - returns summarized, relevant results.
    """
    
    def __init__(self):
        self._api_key = os.getenv("TAVILY_API_KEY", "")
        self._base_url = "https://api.tavily.com"
    
    def initialize(self) -> None:
        """Check if API key is configured."""
        if not self._api_key:
            raise RuntimeError(
                "TAVILY_API_KEY nicht gesetzt. "
                "Hole einen kostenlosen Key von https://tavily.com (1000 Suchen/Monat gratis)"
            )
        masked_key = self._api_key[:4] + "..." + self._api_key[-4:] if len(self._api_key) > 8 else "***"
        logger.info(f"✓ Web-Recherche-Tool initialisiert (Key: {masked_key})")
    
    def _make_request(self, endpoint: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Make HTTP POST request to Tavily API."""
        url = f"{self._base_url}/{endpoint}"
        
        # Add API key to request
        data["api_key"] = self._api_key
        
        try:
            request = urllib.request.Request(
                url,
                data=json.dumps(data).encode('utf-8'),
                headers={
                    "Content-Type": "application/json"
                },
                method="POST"
            )
            
            with urllib.request.urlopen(request, timeout=15) as response:
                result = json.loads(response.read().decode())
                return result
                
        except urllib.error.HTTPError as e:
            error_body = e.read().decode() if e.fp else ""
            logger.error(f"Tavily API-Fehler {e.code}: {error_body}")
            return None
        except Exception as e:
            logger.error(f"Web-Suche fehlgeschlagen: {e}")
            return None
    
    def _format_results(self, data: Dict[str, Any], include_content: bool = True) -> str:
        """Format search results to readable text."""
        if not data:
            return "Die Web-Suche konnte nicht durchgeführt werden."
        
        results = []
        
        # Add AI-generated answer if available
        answer = data.get("answer")
        if answer:
            results.append(f"Zusammenfassung: {answer}")
        
        # Add individual results
        search_results = data.get("results", [])
        
        if search_results and include_content:
            results.append("\nQuellen:")
            for i, result in enumerate(search_results[:3], 1):
                title = result.get("title", "Ohne Titel")
                content = result.get("content", "")
                
                # Truncate content for voice output
                if content and len(content) > 200:
                    content = content[:200].rsplit(' ', 1)[0] + "..."
                
                if content:
                    results.append(f"{i}. {title}: {content}")
                else:
                    results.append(f"{i}. {title}")
        
        if not results:
            return "Keine relevanten Ergebnisse gefunden."
        
        return " ".join(results)
    
    # === Tool Functions for Gemini ===
    
    def search(self, query: str, search_depth: str = "basic") -> str:
        """
        Search the web for current information.
        
        Args:
            query: Search query
            search_depth: "basic" (fast) or "advanced" (thorough)
            
        Returns:
            Search results with summary
        """
        if not query or not query.strip():
            return "Bitte gib eine Suchanfrage an."
        
        logger.info(f"🔍 Web-Suche: {query}")
        
        data = {
            "query": query,
            "search_depth": search_depth,
            "include_answer": True,
            "include_raw_content": False,
            "max_results": 5,
        }
        
        result = self._make_request("search", data)
        
        if not result:
            return f"Die Suche nach '{query}' ist fehlgeschlagen. Bitte versuche es später erneut."
        
        return self._format_results(result)
    
    def search_news(self, query: str) -> str:
        """
        Search for recent news on a topic.
        
        Args:
            query: News topic to search
            
        Returns:
            Recent news results
        """
        if not query or not query.strip():
            return "Bitte gib ein Thema für die Nachrichtensuche an."
        
        logger.info(f"🔍 Nachrichten-Suche: {query}")
        
        data = {
            "query": query,
            "search_depth": "basic",
            "include_answer": True,
            "include_raw_content": False,
            "max_results": 5,
            "topic": "news",  # Focus on news
        }
        
        result = self._make_request("search", data)
        
        if not result:
            return f"Die Nachrichtensuche zu '{query}' ist fehlgeschlagen."
        
        return self._format_results(result)
    
    def quick_answer(self, question: str) -> str:
        """
        Get a quick answer to a factual question.
        
        Args:
            question: Question to answer
            
        Returns:
            Direct answer
        """
        if not question or not question.strip():
            return "Bitte stelle eine Frage."
        
        logger.info(f"🔍 Schnellantwort: {question}")
        
        data = {
            "query": question,
            "search_depth": "basic",
            "include_answer": True,
            "include_raw_content": False,
            "max_results": 3,
        }
        
        result = self._make_request("search", data)
        
        if not result:
            return "Die Suche ist fehlgeschlagen."
        
        # Prioritize the AI answer
        answer = result.get("answer")
        if answer:
            return answer
        
        # Fallback to first result content
        results = result.get("results", [])
        if results and results[0].get("content"):
            return results[0]["content"][:500]
        
        return "Keine Antwort gefunden."
    
    def get_tool_definitions(self) -> list[dict]:
        """Return tool definitions for Gemini."""
        return [
            {
                "name": "web_search",
                "description": "Durchsucht das Internet nach aktuellen Informationen. Nutze dies für Fragen zu aktuellen Ereignissen, Fakten die du nicht weißt, oder wenn der Benutzer explizit nach einer Web-Suche fragt. Beispiele: 'Suche nach den neuesten iPhone Gerüchten', 'Wer hat gestern das Fußballspiel gewonnen?', 'Recherchiere über Quantencomputer'",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Die Suchanfrage"
                        },
                        "search_depth": {
                            "type": "string",
                            "enum": ["basic", "advanced"],
                            "description": "Suchtiefe: 'basic' für schnelle Suche, 'advanced' für gründlichere Recherche"
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "web_search_news",
                "description": "Sucht nach aktuellen Nachrichten zu einem Thema im Internet. Beispiele: 'Aktuelle Nachrichten zu Tesla', 'News über die Bundestagswahl'",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Das Nachrichtenthema"
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "quick_answer",
                "description": "Beantwortet eine faktische Frage durch Web-Suche. Nutze dies für einfache Faktenfragen. Beispiele: 'Wie hoch ist der Eiffelturm?', 'Wann wurde Einstein geboren?', 'Was ist die Hauptstadt von Australien?'",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": "Die zu beantwortende Frage"
                        }
                    },
                    "required": ["question"]
                }
            }
        ]
    
    def get_tool_handlers(self) -> dict[str, Callable]:
        """Return mapping of tool names to handler functions."""
        return {
            "web_search": self.search,
            "web_search_news": self.search_news,
            "quick_answer": self.quick_answer,
        }
    
    def cleanup(self) -> None:
        """Clean up resources."""
        pass
