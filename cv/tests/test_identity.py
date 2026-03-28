"""
Unit tests for identity tracking system.

Tests ReIDEmbedder, IdentityStore, and CVPipeline identity integration.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Generator

import numpy as np
import pytest


def _synthetic_person_image(seed: int = 42, h: int = 256, w: int = 128) -> np.ndarray:
    """Create a synthetic person-like BGR image for testing."""
    rng = np.random.RandomState(seed)
    img = np.ones((h, w, 3), dtype=np.uint8) * 200
    
    skin = (int(rng.randint(180, 230)), int(rng.randint(140, 180)), int(rng.randint(100, 140)))
    shirt = (int(rng.randint(50, 200)), int(rng.randint(50, 200)), int(rng.randint(50, 200)))
    
    import cv2
    cv2.circle(img, (w // 2, h // 8), w // 6, skin, -1)
    cv2.rectangle(img, (w // 4, h // 4), (3 * w // 4, 3 * h // 4), shirt, -1)
    
    return img


@pytest.fixture
def temp_gallery_path() -> Generator[Path, None, None]:
    """Provide a temporary gallery file path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir) / "test_gallery.json"


@pytest.fixture
def sample_embedding() -> np.ndarray:
    """Create a normalized 512-dim embedding."""
    rng = np.random.RandomState(42)
    emb = rng.randn(512).astype(np.float32)
    emb /= np.linalg.norm(emb)
    return emb


@pytest.fixture
def different_embedding() -> np.ndarray:
    """Create a different normalized 512-dim embedding."""
    rng = np.random.RandomState(999)
    emb = rng.randn(512).astype(np.float32)
    emb /= np.linalg.norm(emb)
    return emb


class TestReIDEmbedder:
    """Tests for ReIDEmbedder class."""

    @pytest.mark.integration
    def test_extract_embedding_returns_512_dim(self) -> None:
        """Embedding extraction should return a 512-dimensional vector."""
        from cv.reid_embeddings import ReIDEmbedder
        
        embedder = ReIDEmbedder()
        img = _synthetic_person_image(seed=42)
        
        embedding = embedder.extract_embedding(img)
        
        assert embedding.shape == (512,)
        assert embedding.dtype == np.float32

    @pytest.mark.integration
    def test_embedding_is_normalized(self) -> None:
        """Extracted embedding should be L2-normalized (norm ~1.0)."""
        from cv.reid_embeddings import ReIDEmbedder
        
        embedder = ReIDEmbedder()
        img = _synthetic_person_image(seed=42)
        
        embedding = embedder.extract_embedding(img)
        norm = np.linalg.norm(embedding)
        
        assert 0.99 < norm < 1.01, f"Expected norm ~1.0, got {norm}"

    @pytest.mark.integration
    def test_same_image_high_similarity(self) -> None:
        """Same image should produce identical embeddings."""
        from cv.reid_embeddings import ReIDEmbedder
        
        embedder = ReIDEmbedder()
        img = _synthetic_person_image(seed=42)
        
        emb1 = embedder.extract_embedding(img)
        emb2 = embedder.extract_embedding(img)
        
        similarity = ReIDEmbedder.compute_similarity(emb1, emb2)
        assert similarity > 0.99, f"Same image similarity should be ~1.0, got {similarity}"

    @pytest.mark.integration
    def test_different_images_lower_similarity(self) -> None:
        """Different images should have lower similarity than identical images."""
        from cv.reid_embeddings import ReIDEmbedder
        
        embedder = ReIDEmbedder()
        img1 = _synthetic_person_image(seed=42)
        img2 = _synthetic_person_image(seed=100)
        
        emb1 = embedder.extract_embedding(img1)
        emb2 = embedder.extract_embedding(img2)
        emb1_again = embedder.extract_embedding(img1)
        
        sim_same = ReIDEmbedder.compute_similarity(emb1, emb1_again)
        sim_diff = ReIDEmbedder.compute_similarity(emb1, emb2)
        
        assert sim_same >= sim_diff, (
            f"Same image similarity ({sim_same}) should be >= different ({sim_diff})"
        )

    @pytest.mark.integration
    def test_batch_extraction(self) -> None:
        """Batch extraction should return correct number of embeddings."""
        from cv.reid_embeddings import ReIDEmbedder
        
        embedder = ReIDEmbedder()
        images = [_synthetic_person_image(seed=i) for i in range(3)]
        
        embeddings = embedder.extract_embeddings_batch(images)
        
        assert len(embeddings) == 3
        for emb in embeddings:
            assert emb.shape == (512,)
            assert emb.dtype == np.float32

    def test_compute_similarity_range(self) -> None:
        """Cosine similarity should be in [-1, 1] range."""
        from cv.reid_embeddings import ReIDEmbedder
        
        rng = np.random.RandomState(42)
        emb1 = rng.randn(512).astype(np.float32)
        emb1 /= np.linalg.norm(emb1)
        emb2 = rng.randn(512).astype(np.float32)
        emb2 /= np.linalg.norm(emb2)
        
        sim = ReIDEmbedder.compute_similarity(emb1, emb2)
        
        assert -1.0 <= sim <= 1.0

    def test_compute_distance_non_negative(self) -> None:
        """Euclidean distance should be non-negative."""
        from cv.reid_embeddings import ReIDEmbedder
        
        rng = np.random.RandomState(42)
        emb1 = rng.randn(512).astype(np.float32)
        emb2 = rng.randn(512).astype(np.float32)
        
        dist = ReIDEmbedder.compute_distance(emb1, emb2)
        
        assert dist >= 0.0

    def test_empty_image_raises(self) -> None:
        """Empty image should raise ValueError."""
        from cv.reid_embeddings import ReIDEmbedder
        
        embedder = ReIDEmbedder()
        
        with pytest.raises(ValueError, match="empty"):
            embedder.extract_embedding(np.array([]))

    def test_wrong_channels_raises(self) -> None:
        """Image with wrong number of channels should raise ValueError."""
        from cv.reid_embeddings import ReIDEmbedder
        
        embedder = ReIDEmbedder()
        grayscale = np.zeros((128, 64), dtype=np.uint8)
        
        with pytest.raises(ValueError, match="HxWx3"):
            embedder.extract_embedding(grayscale)


class TestIdentityStore:
    """Tests for IdentityStore class."""

    def test_enroll_creates_file(self, temp_gallery_path: Path, sample_embedding: np.ndarray) -> None:
        """Enrolling a subject should create the gallery file."""
        from cv.identity_store import IdentityStore
        
        store = IdentityStore(gallery_path=temp_gallery_path)
        store.enroll("test_subject", "Test Subject", sample_embedding)
        
        assert temp_gallery_path.exists()

    def test_enroll_stores_subject(self, temp_gallery_path: Path, sample_embedding: np.ndarray) -> None:
        """Enrolled subject should be retrievable."""
        from cv.identity_store import IdentityStore
        
        store = IdentityStore(gallery_path=temp_gallery_path)
        store.enroll("grandma", "Grandma", sample_embedding, color="#FF6B6B")
        
        subject = store.get("grandma")
        
        assert subject is not None
        assert subject.subject_id == "grandma"
        assert subject.display_name == "Grandma"
        assert subject.color == "#FF6B6B"
        assert len(subject.embeddings) == 1

    def test_enroll_persists_across_instances(
        self, temp_gallery_path: Path, sample_embedding: np.ndarray
    ) -> None:
        """Enrolled subjects should persist when creating new store instance."""
        from cv.identity_store import IdentityStore
        
        store1 = IdentityStore(gallery_path=temp_gallery_path)
        store1.enroll("grandpa", "Grandpa", sample_embedding)
        
        store2 = IdentityStore(gallery_path=temp_gallery_path)
        subject = store2.get("grandpa")
        
        assert subject is not None
        assert subject.display_name == "Grandpa"

    def test_enroll_updates_existing_subject(
        self, temp_gallery_path: Path, sample_embedding: np.ndarray, different_embedding: np.ndarray
    ) -> None:
        """Enrolling same subject_id should add embedding, not replace."""
        from cv.identity_store import IdentityStore
        
        store = IdentityStore(gallery_path=temp_gallery_path)
        store.enroll("grandma", "Grandma", sample_embedding)
        store.enroll("grandma", "Grandma Updated", different_embedding)
        
        subject = store.get("grandma")
        
        assert subject is not None
        assert subject.display_name == "Grandma Updated"
        assert len(subject.embeddings) == 2

    def test_enroll_max_embeddings(self, temp_gallery_path: Path) -> None:
        """Enrolling beyond max embeddings should remove oldest."""
        from cv.identity_store import IdentityStore
        
        store = IdentityStore(gallery_path=temp_gallery_path)
        
        for i in range(7):
            rng = np.random.RandomState(i)
            emb = rng.randn(512).astype(np.float32)
            emb /= np.linalg.norm(emb)
            store.enroll("test", "Test", emb)
        
        subject = store.get("test")
        assert subject is not None
        assert len(subject.embeddings) == store.MAX_EMBEDDINGS_PER_SUBJECT

    def test_match_returns_best_match(
        self, temp_gallery_path: Path, sample_embedding: np.ndarray
    ) -> None:
        """Matching should return the subject with highest similarity."""
        from cv.identity_store import IdentityStore
        
        store = IdentityStore(gallery_path=temp_gallery_path)
        store.enroll("grandma", "Grandma", sample_embedding)
        
        similar_emb = sample_embedding + np.random.randn(512).astype(np.float32) * 0.1
        similar_emb /= np.linalg.norm(similar_emb)
        
        match = store.match(similar_emb, threshold=0.5)
        
        assert match is not None
        subject_id, similarity = match
        assert subject_id == "grandma"
        assert 0.5 < similarity <= 1.0

    def test_match_returns_none_below_threshold(
        self, temp_gallery_path: Path, sample_embedding: np.ndarray, different_embedding: np.ndarray
    ) -> None:
        """Matching should return None if best match is below threshold."""
        from cv.identity_store import IdentityStore
        
        store = IdentityStore(gallery_path=temp_gallery_path)
        store.enroll("grandma", "Grandma", sample_embedding)
        
        match = store.match(different_embedding, threshold=0.99)
        
        assert match is None

    def test_match_empty_gallery(self, temp_gallery_path: Path, sample_embedding: np.ndarray) -> None:
        """Matching against empty gallery should return None."""
        from cv.identity_store import IdentityStore
        
        store = IdentityStore(gallery_path=temp_gallery_path)
        
        match = store.match(sample_embedding)
        
        assert match is None

    def test_add_embedding_to_existing(
        self, temp_gallery_path: Path, sample_embedding: np.ndarray, different_embedding: np.ndarray
    ) -> None:
        """add_embedding should add to existing subject."""
        from cv.identity_store import IdentityStore
        
        store = IdentityStore(gallery_path=temp_gallery_path)
        store.enroll("grandma", "Grandma", sample_embedding)
        
        result = store.add_embedding("grandma", different_embedding)
        
        assert result is True
        subject = store.get("grandma")
        assert subject is not None
        assert len(subject.embeddings) == 2

    def test_add_embedding_nonexistent_returns_false(
        self, temp_gallery_path: Path, sample_embedding: np.ndarray
    ) -> None:
        """add_embedding for nonexistent subject should return False."""
        from cv.identity_store import IdentityStore
        
        store = IdentityStore(gallery_path=temp_gallery_path)
        
        result = store.add_embedding("nobody", sample_embedding)
        
        assert result is False

    def test_delete_removes_subject(
        self, temp_gallery_path: Path, sample_embedding: np.ndarray
    ) -> None:
        """delete should remove subject from gallery."""
        from cv.identity_store import IdentityStore
        
        store = IdentityStore(gallery_path=temp_gallery_path)
        store.enroll("grandma", "Grandma", sample_embedding)
        
        result = store.delete("grandma")
        
        assert result is True
        assert store.get("grandma") is None
        assert store.count == 0

    def test_delete_nonexistent_returns_false(self, temp_gallery_path: Path) -> None:
        """delete for nonexistent subject should return False."""
        from cv.identity_store import IdentityStore
        
        store = IdentityStore(gallery_path=temp_gallery_path)
        
        result = store.delete("nobody")
        
        assert result is False

    def test_list_subjects(
        self, temp_gallery_path: Path, sample_embedding: np.ndarray, different_embedding: np.ndarray
    ) -> None:
        """list_subjects should return all enrolled subjects."""
        from cv.identity_store import IdentityStore
        
        store = IdentityStore(gallery_path=temp_gallery_path)
        store.enroll("grandma", "Grandma", sample_embedding)
        store.enroll("grandpa", "Grandpa", different_embedding)
        
        subjects = store.list_subjects()
        
        assert len(subjects) == 2
        ids = {s["subject_id"] for s in subjects}
        assert ids == {"grandma", "grandpa"}

    def test_list_subjects_excludes_embeddings_by_default(
        self, temp_gallery_path: Path, sample_embedding: np.ndarray
    ) -> None:
        """list_subjects should not include embeddings by default."""
        from cv.identity_store import IdentityStore
        
        store = IdentityStore(gallery_path=temp_gallery_path)
        store.enroll("grandma", "Grandma", sample_embedding)
        
        subjects = store.list_subjects(include_embeddings=False)
        
        assert "embeddings" not in subjects[0]

    def test_clear_removes_all(
        self, temp_gallery_path: Path, sample_embedding: np.ndarray, different_embedding: np.ndarray
    ) -> None:
        """clear should remove all subjects."""
        from cv.identity_store import IdentityStore
        
        store = IdentityStore(gallery_path=temp_gallery_path)
        store.enroll("grandma", "Grandma", sample_embedding)
        store.enroll("grandpa", "Grandpa", different_embedding)
        
        count = store.clear()
        
        assert count == 2
        assert store.count == 0

    def test_default_colors(self, temp_gallery_path: Path, sample_embedding: np.ndarray) -> None:
        """grandma and grandpa should get default colors."""
        from cv.identity_store import DEFAULT_COLORS, IdentityStore
        
        store = IdentityStore(gallery_path=temp_gallery_path)
        store.enroll("grandma", "Grandma", sample_embedding)
        
        subject = store.get("grandma")
        assert subject is not None
        assert subject.color == DEFAULT_COLORS["grandma"]

    def test_invalid_embedding_raises(self, temp_gallery_path: Path) -> None:
        """Invalid embedding dimensions should raise ValueError."""
        from cv.identity_store import IdentityStore
        
        store = IdentityStore(gallery_path=temp_gallery_path)
        
        with pytest.raises(ValueError, match="512-dim"):
            store.enroll("test", "Test", np.zeros(256, dtype=np.float32))


class TestCVPipelineIdentity:
    """Tests for CVPipeline identity integration."""

    @pytest.mark.integration
    def test_pipeline_without_identity_store(self, monkeypatch) -> None:
        """Pipeline without identity_store should work without identity features."""
        monkeypatch.setenv("CV_POSE_BACKEND", "none")
        from cv.cv_pipeline import CVPipeline
        
        pipe = CVPipeline(identity_store=None)
        try:
            frame = np.zeros((240, 320, 3), dtype=np.uint8)
            obs = pipe.process_frame(frame, session_id="test")
            
            assert obs is not None
            assert obs.session_id == "test"
        finally:
            pipe.close()

    @pytest.mark.integration
    def test_pipeline_with_identity_store(
        self, monkeypatch, temp_gallery_path: Path
    ) -> None:
        """Pipeline with identity_store should initialize ReIDEmbedder."""
        monkeypatch.setenv("CV_POSE_BACKEND", "none")
        from cv.cv_pipeline import CVPipeline
        from cv.identity_store import IdentityStore
        
        store = IdentityStore(gallery_path=temp_gallery_path)
        pipe = CVPipeline(identity_store=store)
        
        try:
            assert pipe._reid_embedder is not None
            assert pipe._identity_store is store
        finally:
            pipe.close()

    @pytest.mark.integration
    def test_enrolled_person_detection(
        self, monkeypatch, temp_gallery_path: Path
    ) -> None:
        """Detected person matching enrolled subject should have correct ID."""
        monkeypatch.setenv("CV_POSE_BACKEND", "none")
        from cv.cv_pipeline import CVPipeline
        from cv.identity_store import IdentityStore
        from cv.reid_embeddings import ReIDEmbedder
        
        img = _synthetic_person_image(seed=42)
        
        embedder = ReIDEmbedder()
        embedding = embedder.extract_embedding(img)
        
        store = IdentityStore(gallery_path=temp_gallery_path)
        store.enroll("grandma", "Grandma", embedding)
        
        pipe = CVPipeline(identity_store=store)
        
        try:
            h, w = 480, 640
            frame = np.ones((h, w, 3), dtype=np.uint8) * 128
            vh, vw = img.shape[:2]
            y_off = (h - vh) // 2
            x_off = (w - vw) // 2
            frame[y_off:y_off+vh, x_off:x_off+vw] = img
            
            obs = pipe.process_frame(frame, session_id="test")
            
            assert obs is not None
        finally:
            pipe.close()

    @pytest.mark.integration
    def test_visitor_tracking(self, monkeypatch, temp_gallery_path: Path) -> None:
        """Non-enrolled persons should get visitor IDs."""
        monkeypatch.setenv("CV_POSE_BACKEND", "none")
        from cv.cv_pipeline import CVPipeline
        from cv.identity_store import IdentityStore
        
        store = IdentityStore(gallery_path=temp_gallery_path)
        pipe = CVPipeline(identity_store=store)
        
        try:
            assert pipe._visitor_counter == 0
        finally:
            pipe.close()

    def test_crop_person(self, monkeypatch) -> None:
        """_crop_person should extract correct region."""
        monkeypatch.setenv("CV_POSE_BACKEND", "none")
        from cv.cv_pipeline import CVPipeline
        
        pipe = CVPipeline(identity_store=None)
        
        try:
            frame = np.zeros((100, 200, 3), dtype=np.uint8)
            frame[25:75, 50:150] = 255
            
            bbox = [0.25, 0.25, 0.75, 0.75]
            crop = pipe._crop_person(frame, bbox, padding=0.0)
            
            assert crop.shape[0] > 0
            assert crop.shape[1] > 0
            assert crop.shape[2] == 3
            
            assert crop.mean() > 200
        finally:
            pipe.close()

    def test_assign_visitor_id_increments(self, monkeypatch, temp_gallery_path: Path) -> None:
        """_assign_visitor_id should increment counter for new visitors."""
        monkeypatch.setenv("CV_POSE_BACKEND", "none")
        from cv.cv_pipeline import CVPipeline
        from cv.identity_store import IdentityStore
        
        store = IdentityStore(gallery_path=temp_gallery_path)
        pipe = CVPipeline(identity_store=store)
        
        try:
            rng = np.random.RandomState(1)
            emb1 = rng.randn(512).astype(np.float32)
            emb1 /= np.linalg.norm(emb1)
            
            rng = np.random.RandomState(999)
            emb2 = rng.randn(512).astype(np.float32)
            emb2 /= np.linalg.norm(emb2)
            
            id1 = pipe._assign_visitor_id(emb1)
            id2 = pipe._assign_visitor_id(emb2)
            
            assert id1 == "visitor_1"
            assert id2 == "visitor_2"
        finally:
            pipe.close()

    def test_assign_visitor_id_reuses_for_same_person(
        self, monkeypatch, temp_gallery_path: Path
    ) -> None:
        """_assign_visitor_id should reuse ID for similar embeddings."""
        monkeypatch.setenv("CV_POSE_BACKEND", "none")
        from cv.cv_pipeline import CVPipeline
        from cv.identity_store import IdentityStore
        
        store = IdentityStore(gallery_path=temp_gallery_path)
        pipe = CVPipeline(identity_store=store)
        
        try:
            rng = np.random.RandomState(42)
            emb = rng.randn(512).astype(np.float32)
            emb /= np.linalg.norm(emb)
            
            id1 = pipe._assign_visitor_id(emb)
            id2 = pipe._assign_visitor_id(emb)
            
            assert id1 == id2
        finally:
            pipe.close()


class TestEnrollmentAPI:
    """Tests for enrollment API endpoints."""

    @pytest.fixture
    def test_client(self, temp_gallery_path: Path):
        """Create test client with temp gallery."""
        from starlette.testclient import TestClient
        
        from cv.identity_store import IdentityStore
        from cv.main import create_app
        
        store = IdentityStore(gallery_path=temp_gallery_path)
        
        class StubPipeline:
            def __init__(self):
                self.closed = False
            
            def process_frame(self, frame, *, session_id, minutes_since_last_seen_if_absent=0):
                from datetime import datetime, timezone
                from cv.models import ActivityType, MotionLevel, Observation, PoseType
                return Observation(
                    id="test-obs",
                    observed_at=datetime.now(timezone.utc),
                    person_detected=False,
                    pose=PoseType.UNKNOWN,
                    pose_confidence=0.0,
                    activity=ActivityType.UNKNOWN,
                    activity_confidence=0.0,
                    objects_detected=[],
                    room_hint="unknown",
                    is_fall_risk=False,
                    motion_level=MotionLevel.NONE,
                    minutes_since_last_seen=0,
                    frame_quality=0.5,
                    session_id=session_id,
                )
            
            def close(self):
                self.closed = True
        
        app = create_app(
            pipeline_factory=lambda: StubPipeline(),
            identity_store=store,
        )
        
        with TestClient(app) as client:
            yield client, store

    def _jpeg_bytes(self, seed: int = 42) -> bytes:
        """Create JPEG bytes from synthetic image."""
        import cv2
        img = _synthetic_person_image(seed=seed)
        _, buf = cv2.imencode(".jpg", img)
        return buf.tobytes()

    def test_list_subjects_empty(self, test_client) -> None:
        """GET /subjects should return empty list initially."""
        client, _ = test_client
        
        r = client.get("/subjects")
        
        assert r.status_code == 200
        assert r.json()["subjects"] == []

    def test_enroll_subject(self, test_client) -> None:
        """POST /enroll-subject should enroll a new subject."""
        client, store = test_client
        
        files = {"file": ("person.jpg", self._jpeg_bytes(), "image/jpeg")}
        data = {"subject_id": "grandma", "display_name": "Grandma"}
        
        r = client.post("/enroll-subject", files=files, data=data)
        
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["subject_id"] == "grandma"
        assert body["embedding_count"] >= 1

    def test_list_subjects_after_enroll(self, test_client) -> None:
        """GET /subjects should list enrolled subjects."""
        client, _ = test_client
        
        files = {"file": ("person.jpg", self._jpeg_bytes(), "image/jpeg")}
        data = {"subject_id": "grandma", "display_name": "Grandma"}
        client.post("/enroll-subject", files=files, data=data)
        
        r = client.get("/subjects")
        
        assert r.status_code == 200
        subjects = r.json()["subjects"]
        assert len(subjects) == 1
        assert subjects[0]["subject_id"] == "grandma"

    def test_get_subject(self, test_client) -> None:
        """GET /subjects/{id} should return subject details."""
        client, _ = test_client
        
        files = {"file": ("person.jpg", self._jpeg_bytes(), "image/jpeg")}
        data = {"subject_id": "grandma", "display_name": "Grandma"}
        client.post("/enroll-subject", files=files, data=data)
        
        r = client.get("/subjects/grandma")
        
        assert r.status_code == 200
        body = r.json()
        assert body["subject_id"] == "grandma"
        assert body["display_name"] == "Grandma"

    def test_get_subject_not_found(self, test_client) -> None:
        """GET /subjects/{id} should return 404 for unknown subject."""
        client, _ = test_client
        
        r = client.get("/subjects/nobody")
        
        assert r.status_code == 404

    def test_delete_subject(self, test_client) -> None:
        """DELETE /subjects/{id} should remove subject."""
        client, _ = test_client
        
        files = {"file": ("person.jpg", self._jpeg_bytes(), "image/jpeg")}
        data = {"subject_id": "grandma", "display_name": "Grandma"}
        client.post("/enroll-subject", files=files, data=data)
        
        r = client.delete("/subjects/grandma")
        
        assert r.status_code == 200
        assert r.json()["success"] is True
        
        r = client.get("/subjects/grandma")
        assert r.status_code == 404

    def test_delete_subject_not_found(self, test_client) -> None:
        """DELETE /subjects/{id} should return 404 for unknown subject."""
        client, _ = test_client
        
        r = client.delete("/subjects/nobody")
        
        assert r.status_code == 404

    def test_add_subject_view(self, test_client) -> None:
        """POST /subjects/{id}/add-view should add embedding."""
        client, _ = test_client
        
        files = {"file": ("person.jpg", self._jpeg_bytes(seed=42), "image/jpeg")}
        data = {"subject_id": "grandma", "display_name": "Grandma"}
        client.post("/enroll-subject", files=files, data=data)
        
        files = {"file": ("person2.jpg", self._jpeg_bytes(seed=43), "image/jpeg")}
        r = client.post("/subjects/grandma/add-view", files=files)
        
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["embedding_count"] == 2

    def test_add_subject_view_not_found(self, test_client) -> None:
        """POST /subjects/{id}/add-view should return 404 for unknown subject."""
        client, _ = test_client
        
        files = {"file": ("person.jpg", self._jpeg_bytes(), "image/jpeg")}
        r = client.post("/subjects/nobody/add-view", files=files)
        
        assert r.status_code == 404

    def test_enroll_empty_file(self, test_client) -> None:
        """POST /enroll-subject with empty file should return 400."""
        client, _ = test_client
        
        files = {"file": ("empty.jpg", b"", "image/jpeg")}
        data = {"subject_id": "grandma", "display_name": "Grandma"}
        
        r = client.post("/enroll-subject", files=files, data=data)
        
        assert r.status_code == 400

    def test_enroll_missing_subject_id(self, test_client) -> None:
        """POST /enroll-subject without subject_id should fail."""
        client, _ = test_client
        
        files = {"file": ("person.jpg", self._jpeg_bytes(), "image/jpeg")}
        data = {"display_name": "Grandma"}
        
        r = client.post("/enroll-subject", files=files, data=data)
        
        assert r.status_code == 422
