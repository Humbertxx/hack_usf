"""
ReID Embedding Extraction using torchreid OSNet.

Provides person re-identification embeddings for identity matching.
Uses OSNet (osnet_x0_25) - a lightweight model (~2MB) optimized for ReID tasks.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import torch
from torch import nn

_CACHE_DIR = Path(__file__).resolve().parent / ".cache" / "reid"


def _device() -> str:
    return "cuda:0" if torch.cuda.is_available() else "cpu"


class ReIDEmbedder:
    """
    Person re-identification embedding extractor using torchreid OSNet.
    
    Extracts 512-dimensional normalized embeddings from person crops
    for identity matching via cosine similarity.
    """

    def __init__(
        self,
        model_name: str = "osnet_x0_25",
        device: str = "auto",
    ) -> None:
        """
        Initialize the ReID embedder.
        
        Args:
            model_name: torchreid model name. Default "osnet_x0_25" is small and fast.
            device: "auto", "cuda:0", "cpu". Auto selects CUDA if available.
        """
        self._model_name = model_name
        self._device_str = device if device != "auto" else _device()
        self._model: Optional[nn.Module] = None
        self._input_size = (256, 128)  # Standard ReID input: height x width

    def _ensure_model(self) -> nn.Module:
        """Lazy load the model on first use."""
        if self._model is not None:
            return self._model

        _CACHE_DIR.mkdir(parents=True, exist_ok=True)

        try:
            import torchreid
        except ImportError as e:
            raise ImportError(
                "torchreid is required for ReID embeddings. "
                "Install with: pip install torchreid"
            ) from e

        self._model = torchreid.models.build_model(
            name=self._model_name,
            num_classes=1,  # Not used for feature extraction
            loss="softmax",
            pretrained=True,
        )
        self._model = self._model.to(self._device_str)
        self._model.eval()

        return self._model

    def _preprocess(self, person_crop: np.ndarray) -> torch.Tensor:
        """
        Preprocess a BGR person crop for the model.
        
        Args:
            person_crop: BGR image (HxWx3 uint8)
            
        Returns:
            Preprocessed tensor ready for model input (1x3xHxW)
        """
        img = cv2.cvtColor(person_crop, cv2.COLOR_BGR2RGB)
        img = cv2.resize(img, (self._input_size[1], self._input_size[0]))
        
        img = img.astype(np.float32) / 255.0
        mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
        std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
        img = (img - mean) / std
        
        img = img.transpose(2, 0, 1)  # HWC -> CHW
        tensor = torch.from_numpy(img).unsqueeze(0)  # Add batch dim
        return tensor.to(self._device_str)

    def extract_embedding(self, person_crop: np.ndarray) -> np.ndarray:
        """
        Extract a 512-dimensional normalized embedding from a person crop.
        
        Args:
            person_crop: BGR image (HxWx3 uint8) containing a person.
                         Should be cropped tightly around the person.
                         
        Returns:
            512-dim L2-normalized embedding as float32 numpy array.
        """
        if person_crop is None or person_crop.size == 0:
            raise ValueError("person_crop cannot be empty")
        
        if person_crop.ndim != 3 or person_crop.shape[2] != 3:
            raise ValueError("person_crop must be HxWx3 BGR image")

        model = self._ensure_model()
        tensor = self._preprocess(person_crop)

        with torch.no_grad():
            features = model(tensor)
            if isinstance(features, tuple):
                features = features[0]
            
            embedding = features.cpu().numpy().flatten()
            norm = np.linalg.norm(embedding)
            if norm > 1e-6:
                embedding = embedding / norm
            
            return embedding.astype(np.float32)

    def extract_embeddings_batch(
        self,
        person_crops: list[np.ndarray],
    ) -> list[np.ndarray]:
        """
        Extract embeddings for multiple person crops in a batch.
        
        Args:
            person_crops: List of BGR images (HxWx3 uint8)
            
        Returns:
            List of 512-dim L2-normalized embeddings.
        """
        if not person_crops:
            return []

        model = self._ensure_model()
        tensors = [self._preprocess(crop) for crop in person_crops]
        batch = torch.cat(tensors, dim=0)

        with torch.no_grad():
            features = model(batch)
            if isinstance(features, tuple):
                features = features[0]
            
            embeddings = features.cpu().numpy()
            norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
            norms = np.maximum(norms, 1e-6)
            embeddings = embeddings / norms
            
            return [emb.astype(np.float32) for emb in embeddings]

    @staticmethod
    def compute_similarity(emb1: np.ndarray, emb2: np.ndarray) -> float:
        """
        Compute cosine similarity between two embeddings.
        
        Args:
            emb1: First embedding (512-dim, should be L2-normalized)
            emb2: Second embedding (512-dim, should be L2-normalized)
            
        Returns:
            Cosine similarity in range [-1, 1], typically [0, 1] for ReID.
            Higher values indicate more similar appearances.
        """
        emb1 = emb1.flatten().astype(np.float64)
        emb2 = emb2.flatten().astype(np.float64)
        
        similarity = float(np.dot(emb1, emb2))
        return max(-1.0, min(1.0, similarity))

    @staticmethod
    def compute_distance(emb1: np.ndarray, emb2: np.ndarray) -> float:
        """
        Compute Euclidean distance between two embeddings.
        
        Args:
            emb1: First embedding (512-dim)
            emb2: Second embedding (512-dim)
            
        Returns:
            Euclidean distance. Lower values indicate more similar appearances.
            For normalized embeddings: distance = sqrt(2 * (1 - similarity))
        """
        emb1 = emb1.flatten().astype(np.float64)
        emb2 = emb2.flatten().astype(np.float64)
        return float(np.linalg.norm(emb1 - emb2))

    @property
    def embedding_dim(self) -> int:
        """Return the embedding dimension (512 for OSNet)."""
        return 512

    @property
    def model_name(self) -> str:
        """Return the model name."""
        return self._model_name

    @property
    def device(self) -> str:
        """Return the device string."""
        return self._device_str
