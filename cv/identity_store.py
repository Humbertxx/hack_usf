"""
Identity Gallery Storage for enrolled subjects.

Provides persistent storage for enrolled subject embeddings with
JSON-based persistence and thread-safe operations.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
from pydantic import BaseModel, Field

_DEFAULT_GALLERY_PATH = Path(__file__).resolve().parent / "data" / "identity_gallery.json"

DEFAULT_COLORS = {
    "grandma": "#FF6B6B",  # Coral
    "grandpa": "#4ECDC4",  # Teal
}


class EnrolledSubject(BaseModel):
    """Represents an enrolled subject in the identity gallery."""

    subject_id: str
    display_name: str
    embeddings: List[List[float]] = Field(default_factory=list)
    enrolled_at: datetime
    color: str

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }


class IdentityStore:
    """
    Persistent storage for enrolled subject identities.
    
    Stores subject embeddings in JSON format for matching against
    detected persons in video frames.
    """

    MAX_EMBEDDINGS_PER_SUBJECT = 5

    def __init__(
        self,
        gallery_path: Optional[Path] = None,
    ) -> None:
        """
        Initialize the identity store.
        
        Args:
            gallery_path: Path to the JSON gallery file. 
                          Defaults to cv/data/identity_gallery.json
        """
        self._gallery_path = gallery_path or _DEFAULT_GALLERY_PATH
        self._lock = threading.RLock()
        self._subjects: dict[str, EnrolledSubject] = {}
        self._load()

    def _load(self) -> None:
        """Load gallery from disk if it exists."""
        if not self._gallery_path.exists():
            return

        try:
            with open(self._gallery_path, "r") as f:
                data = json.load(f)
            
            for subject_data in data.get("subjects", []):
                subject = EnrolledSubject(
                    subject_id=subject_data["subject_id"],
                    display_name=subject_data["display_name"],
                    embeddings=subject_data.get("embeddings", []),
                    enrolled_at=datetime.fromisoformat(subject_data["enrolled_at"]),
                    color=subject_data["color"],
                )
                self._subjects[subject.subject_id] = subject
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            print(f"[IdentityStore] Warning: Failed to load gallery: {e}")

    def _save(self) -> None:
        """Persist gallery to disk."""
        self._gallery_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "version": 1,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "subjects": [
                {
                    "subject_id": s.subject_id,
                    "display_name": s.display_name,
                    "embeddings": s.embeddings,
                    "enrolled_at": s.enrolled_at.isoformat(),
                    "color": s.color,
                }
                for s in self._subjects.values()
            ],
        }

        temp_path = self._gallery_path.with_suffix(".tmp")
        with open(temp_path, "w") as f:
            json.dump(data, f, indent=2)
        temp_path.replace(self._gallery_path)

    def enroll(
        self,
        subject_id: str,
        display_name: str,
        embedding: np.ndarray,
        color: Optional[str] = None,
    ) -> EnrolledSubject:
        """
        Enroll a new subject or update an existing one with a new embedding.
        
        Args:
            subject_id: Unique identifier (e.g., "grandma", "grandpa")
            display_name: Human-readable name (e.g., "Grandma", "Grandpa")
            embedding: 512-dim normalized embedding from ReIDEmbedder
            color: Hex color for bounding box (e.g., "#FF6B6B"). 
                   Defaults based on subject_id or generates one.
                   
        Returns:
            The enrolled or updated subject.
        """
        if embedding.ndim != 1 or len(embedding) != 512:
            raise ValueError("embedding must be a 512-dim vector")

        embedding_list = embedding.astype(np.float32).tolist()

        with self._lock:
            if subject_id in self._subjects:
                subject = self._subjects[subject_id]
                if len(subject.embeddings) < self.MAX_EMBEDDINGS_PER_SUBJECT:
                    subject.embeddings.append(embedding_list)
                else:
                    subject.embeddings.pop(0)
                    subject.embeddings.append(embedding_list)
                subject.display_name = display_name
                if color:
                    subject.color = color
            else:
                if color is None:
                    color = DEFAULT_COLORS.get(subject_id.lower(), self._generate_color(subject_id))
                
                subject = EnrolledSubject(
                    subject_id=subject_id,
                    display_name=display_name,
                    embeddings=[embedding_list],
                    enrolled_at=datetime.now(timezone.utc),
                    color=color,
                )
                self._subjects[subject_id] = subject

            self._save()
            return subject

    def add_embedding(self, subject_id: str, embedding: np.ndarray) -> bool:
        """
        Add an additional embedding view to an existing subject.
        
        Args:
            subject_id: The subject to add the embedding to
            embedding: 512-dim normalized embedding
            
        Returns:
            True if added successfully, False if subject doesn't exist.
        """
        if embedding.ndim != 1 or len(embedding) != 512:
            raise ValueError("embedding must be a 512-dim vector")

        embedding_list = embedding.astype(np.float32).tolist()

        with self._lock:
            if subject_id not in self._subjects:
                return False

            subject = self._subjects[subject_id]
            if len(subject.embeddings) < self.MAX_EMBEDDINGS_PER_SUBJECT:
                subject.embeddings.append(embedding_list)
            else:
                subject.embeddings.pop(0)
                subject.embeddings.append(embedding_list)

            self._save()
            return True

    def best_match(self, embedding: np.ndarray) -> Optional[Tuple[str, float]]:
        """
        Best enrolled subject for this query: max cosine similarity to any stored
        embedding (each enrollment photo is a separate template; multi-view = OR).
        """
        if embedding.ndim != 1 or len(embedding) != 512:
            raise ValueError("embedding must be a 512-dim vector")

        query = embedding.astype(np.float64).flatten()
        query_norm = np.linalg.norm(query)
        if query_norm > 1e-6:
            query = query / query_norm

        best: Optional[Tuple[str, float]] = None
        best_score = -1.0

        with self._lock:
            for subject_id, subject in self._subjects.items():
                if not subject.embeddings:
                    continue

                max_sim = max(
                    float(np.dot(query, np.array(emb_list, dtype=np.float64)))
                    for emb_list in subject.embeddings
                )
                if max_sim > best_score:
                    best_score = max_sim
                    best = (subject_id, max_sim)

        return best

    def match(
        self,
        embedding: np.ndarray,
        threshold: float = 0.65,
    ) -> Optional[Tuple[str, float]]:
        """
        Same as best_match, but returns None unless similarity >= threshold.
        """
        b = self.best_match(embedding)
        if b is None:
            return None
        subject_id, sim = b
        if sim >= threshold:
            return b
        return None

    def get(self, subject_id: str) -> Optional[EnrolledSubject]:
        """
        Get a subject by ID.
        
        Args:
            subject_id: The subject ID to look up
            
        Returns:
            The EnrolledSubject if found, None otherwise.
        """
        with self._lock:
            return self._subjects.get(subject_id)

    def list_subjects(self, include_embeddings: bool = False) -> List[dict]:
        """
        List all enrolled subjects.
        
        Args:
            include_embeddings: If True, include raw embeddings in output.
                               Default False for privacy/size.
                               
        Returns:
            List of subject info dicts.
        """
        with self._lock:
            result = []
            for subject in self._subjects.values():
                info = {
                    "subject_id": subject.subject_id,
                    "display_name": subject.display_name,
                    "color": subject.color,
                    "embedding_count": len(subject.embeddings),
                    "enrolled_at": subject.enrolled_at.isoformat(),
                }
                if include_embeddings:
                    info["embeddings"] = subject.embeddings
                result.append(info)
            return result

    def delete(self, subject_id: str) -> bool:
        """
        Remove an enrolled subject from the gallery.
        
        Args:
            subject_id: The subject to remove
            
        Returns:
            True if removed, False if not found.
        """
        with self._lock:
            if subject_id not in self._subjects:
                return False
            del self._subjects[subject_id]
            self._save()
            return True

    def clear(self) -> int:
        """
        Remove all enrolled subjects.
        
        Returns:
            Number of subjects removed.
        """
        with self._lock:
            count = len(self._subjects)
            self._subjects.clear()
            self._save()
            return count

    def _generate_color(self, subject_id: str) -> str:
        """Generate a deterministic color from subject_id."""
        hash_val = hash(subject_id) % 0xFFFFFF
        return f"#{hash_val:06X}"

    @property
    def count(self) -> int:
        """Return the number of enrolled subjects."""
        with self._lock:
            return len(self._subjects)

    @property
    def gallery_path(self) -> Path:
        """Return the gallery file path."""
        return self._gallery_path
