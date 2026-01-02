"""
Memory Tool for Voice Assistant using ChromaDB.
Provides persistent semantic memory across conversations.
"""

import logging
import os
from datetime import datetime
from typing import Optional
import chromadb
from chromadb.config import Settings

logger = logging.getLogger(__name__)

# Data directory for ChromaDB persistence
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")


class MemoryTool:
    """
    Persistent memory using ChromaDB for semantic search.
    Allows the assistant to remember facts, preferences, and context.
    """
    
    def __init__(self):
        self._client = None
        self._collection = None
    
    def initialize(self) -> None:
        """Initialize ChromaDB with persistent storage."""
        try:
            # Ensure data directory exists
            os.makedirs(DATA_DIR, exist_ok=True)
            
            # Initialize ChromaDB with persistence
            self._client = chromadb.PersistentClient(
                path=os.path.join(DATA_DIR, "memory_db"),
                settings=Settings(anonymized_telemetry=False)
            )
            
            # Get or create the memories collection
            self._collection = self._client.get_or_create_collection(
                name="memories",
                metadata={"description": "User memories and facts"}
            )
            
            count = self._collection.count()
            logger.info(f"✓ Gedächtnis initialisiert ({count} Erinnerungen)")
            
        except Exception as e:
            logger.error(f"Fehler beim Initialisieren des Gedächtnisses: {e}")
            raise
    
    def save_memory(self, content: str, category: str = "general") -> str:
        """
        Save a piece of information to memory.
        
        Args:
            content: The information to remember (e.g., "User wakes up at 7 AM")
            category: Category for organization (e.g., "preference", "fact", "reminder")
            
        Returns:
            Confirmation message
        """
        if not self._collection:
            return "Gedächtnis nicht initialisiert."
        
        try:
            # Generate unique ID based on timestamp
            memory_id = f"mem_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
            
            # Store with metadata
            self._collection.add(
                documents=[content],
                metadatas=[{
                    "category": category,
                    "created_at": datetime.now().isoformat(),
                }],
                ids=[memory_id]
            )
            
            logger.info(f"💾 Erinnerung gespeichert: {content[:50]}...")
            return f"Ich habe mir gemerkt: {content}"
            
        except Exception as e:
            logger.error(f"Fehler beim Speichern: {e}")
            return f"Konnte mir das nicht merken: {e}"
    
    def recall_memory(self, query: str, n_results: int = 3) -> str:
        """
        Search for relevant memories using semantic search.
        
        Args:
            query: What to search for (e.g., "when does user wake up")
            n_results: Maximum number of results to return
            
        Returns:
            Relevant memories or "nothing found" message
        """
        if not self._collection:
            return "Gedächtnis nicht initialisiert."
        
        try:
            # Check if collection is empty
            if self._collection.count() == 0:
                return "Ich habe noch keine Erinnerungen gespeichert."
            
            # Semantic search
            results = self._collection.query(
                query_texts=[query],
                n_results=min(n_results, self._collection.count())
            )
            
            if not results['documents'] or not results['documents'][0]:
                return "Dazu habe ich keine Erinnerung."
            
            # Format results
            memories = results['documents'][0]
            
            if len(memories) == 1:
                return f"Ich erinnere mich: {memories[0]}"
            else:
                formatted = "\n".join([f"- {m}" for m in memories])
                return f"Ich erinnere mich an folgendes:\n{formatted}"
                
        except Exception as e:
            logger.error(f"Fehler beim Abrufen: {e}")
            return f"Fehler beim Erinnern: {e}"
    
    def list_memories(self, limit: int = 10) -> str:
        """
        List all stored memories.
        
        Args:
            limit: Maximum number of memories to list
            
        Returns:
            List of all memories
        """
        if not self._collection:
            return "Gedächtnis nicht initialisiert."
        
        try:
            count = self._collection.count()
            if count == 0:
                return "Ich habe noch keine Erinnerungen gespeichert."
            
            # Get all memories (up to limit)
            results = self._collection.get(
                limit=limit,
                include=["documents", "metadatas"]
            )
            
            if not results['documents']:
                return "Keine Erinnerungen gefunden."
            
            # Format with categories
            memory_list = []
            for doc, meta in zip(results['documents'], results['metadatas']):
                category = meta.get('category', 'general')
                memory_list.append(f"- [{category}] {doc}")
            
            header = f"Meine {len(memory_list)} Erinnerungen"
            if count > limit:
                header += f" (von {count} insgesamt)"
            
            return f"{header}:\n" + "\n".join(memory_list)
            
        except Exception as e:
            logger.error(f"Fehler beim Auflisten: {e}")
            return f"Fehler: {e}"
    
    def forget_memory(self, query: str) -> str:
        """
        Delete a memory matching the query.
        
        Args:
            query: Description of what to forget
            
        Returns:
            Confirmation message
        """
        if not self._collection:
            return "Gedächtnis nicht initialisiert."
        
        try:
            if self._collection.count() == 0:
                return "Ich habe keine Erinnerungen zum Vergessen."
            
            # Find the memory first
            results = self._collection.query(
                query_texts=[query],
                n_results=1
            )
            
            if not results['ids'] or not results['ids'][0]:
                return "Dazu habe ich keine Erinnerung die ich vergessen könnte."
            
            memory_id = results['ids'][0][0]
            memory_content = results['documents'][0][0]
            
            # Delete it
            self._collection.delete(ids=[memory_id])
            
            logger.info(f"🗑️ Erinnerung gelöscht: {memory_content[:50]}...")
            return f"Ich habe vergessen: {memory_content}"
            
        except Exception as e:
            logger.error(f"Fehler beim Vergessen: {e}")
            return f"Konnte nicht vergessen: {e}"
    
    def clear_all_memories(self) -> str:
        """
        Delete all memories. Use with caution!
        
        Returns:
            Confirmation message
        """
        if not self._collection:
            return "Gedächtnis nicht initialisiert."
        
        try:
            count = self._collection.count()
            if count == 0:
                return "Es gibt keine Erinnerungen zum Löschen."
            
            # Delete collection and recreate
            self._client.delete_collection("memories")
            self._collection = self._client.create_collection(
                name="memories",
                metadata={"description": "User memories and facts"}
            )
            
            logger.info(f"🗑️ Alle {count} Erinnerungen gelöscht")
            return f"Ich habe alle {count} Erinnerungen gelöscht."
            
        except Exception as e:
            logger.error(f"Fehler beim Löschen aller Erinnerungen: {e}")
            return f"Fehler: {e}"
    
    def get_tool_definitions(self) -> list[dict]:
        """Return tool definitions for Gemini."""
        return [
            {
                "name": "save_memory",
                "description": "Speichert eine Information dauerhaft im Gedächtnis. Nutze dies wenn der Benutzer sagt 'Merk dir...', 'Erinnere dich...' oder wichtige persönliche Informationen teilt (Name, Präferenzen, Routinen, etc.)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "Die zu merkende Information, z.B. 'Der Benutzer steht um 7 Uhr auf' oder 'Die Schwester heißt Anna'"
                        },
                        "category": {
                            "type": "string",
                            "description": "Kategorie: 'preference' (Vorlieben), 'fact' (Fakten über den Benutzer), 'routine' (Routinen/Gewohnheiten), 'person' (Personen), 'general' (Sonstiges)",
                            "enum": ["preference", "fact", "routine", "person", "general"]
                        }
                    },
                    "required": ["content"]
                }
            },
            {
                "name": "recall_memory",
                "description": "Sucht im Gedächtnis nach relevanten Erinnerungen. Nutze dies bei Fragen wie 'Weißt du noch...', 'Wann...', 'Wie heißt...' oder wenn Kontext aus früheren Gesprächen benötigt wird.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Wonach gesucht werden soll, z.B. 'Aufstehzeit' oder 'Name der Schwester'"
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "list_memories",
                "description": "Listet alle gespeicherten Erinnerungen auf. Nutze dies wenn der Benutzer fragt 'Was weißt du über mich?' oder 'Was hast du dir gemerkt?'",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "Maximale Anzahl der aufzulistenden Erinnerungen (Standard: 10)"
                        }
                    }
                }
            },
            {
                "name": "forget_memory",
                "description": "Löscht eine bestimmte Erinnerung. Nutze dies wenn der Benutzer sagt 'Vergiss...' oder eine Information nicht mehr gespeichert sein soll.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Beschreibung der zu vergessenden Erinnerung"
                        }
                    },
                    "required": ["query"]
                }
            }
        ]
    
    def get_tool_handlers(self) -> dict:
        """Return mapping of tool names to handler functions."""
        return {
            "save_memory": self.save_memory,
            "recall_memory": self.recall_memory,
            "list_memories": self.list_memories,
            "forget_memory": self.forget_memory,
        }
