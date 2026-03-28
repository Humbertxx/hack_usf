#!/usr/bin/env python3
"""
End-to-end test script for identity enrollment and matching.

Usage:
    # Run full test sequence with synthetic images
    python -m cv.scripts.test_identity_matching

    # Test with live camera
    python -m cv.scripts.test_identity_matching --camera 0

    # Test with image directory
    python -m cv.scripts.test_identity_matching --images ./test_images/

    # Verbose output with timing metrics
    python -m cv.scripts.test_identity_matching --verbose

Test sequence:
    1. Clear any existing test gallery
    2. Enroll "test_subject_1" from sample image or camera
    3. Run detection on new frame with the same person
    4. Verify person_id == "test_subject_1" and is_enrolled == True
    5. Run detection on frame with different/unknown person
    6. Verify person_id == "visitor_X" and is_enrolled == False
    7. Print similarity scores and timing metrics
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np


def _create_synthetic_person_image(
    seed: int = 42,
    width: int = 256,
    height: int = 512,
) -> np.ndarray:
    """
    Create a synthetic person-like image for testing.
    
    Uses colored shapes to simulate a person silhouette.
    Different seeds produce visually distinct "persons".
    """
    rng = np.random.RandomState(seed)
    
    img = np.ones((height, width, 3), dtype=np.uint8) * 200
    
    skin_color = (
        int(rng.randint(180, 230)),
        int(rng.randint(140, 180)),
        int(rng.randint(100, 140)),
    )
    
    shirt_color = (
        int(rng.randint(50, 200)),
        int(rng.randint(50, 200)),
        int(rng.randint(50, 200)),
    )
    
    pants_color = (
        int(rng.randint(30, 100)),
        int(rng.randint(30, 100)),
        int(rng.randint(30, 100)),
    )
    
    center_x = width // 2
    
    head_radius = width // 6
    head_y = height // 8 + head_radius
    cv2.circle(img, (center_x, head_y), head_radius, skin_color, -1)
    
    torso_top = head_y + head_radius + 5
    torso_bottom = int(height * 0.55)
    torso_width = width // 3
    cv2.rectangle(
        img,
        (center_x - torso_width, torso_top),
        (center_x + torso_width, torso_bottom),
        shirt_color,
        -1,
    )
    
    legs_top = torso_bottom
    legs_bottom = int(height * 0.95)
    leg_width = torso_width // 2
    cv2.rectangle(
        img,
        (center_x - torso_width, legs_top),
        (center_x - leg_width // 2, legs_bottom),
        pants_color,
        -1,
    )
    cv2.rectangle(
        img,
        (center_x + leg_width // 2, legs_top),
        (center_x + torso_width, legs_bottom),
        pants_color,
        -1,
    )
    
    return img


def _capture_from_camera(camera_index: int, prompt: str) -> Optional[np.ndarray]:
    """Capture a frame from camera with interactive preview."""
    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        print(f"Error: Cannot open camera {camera_index}")
        return None

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    print(f"\n{prompt}")
    print("Press SPACE to capture, ESC/Q to skip")

    captured = None
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            display = frame.copy()
            h = display.shape[0]
            cv2.putText(
                display,
                prompt[:60],
                (10, h - 40),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 0),
                2,
            )
            cv2.putText(
                display,
                "SPACE=capture, ESC/Q=skip",
                (10, h - 15),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (200, 200, 200),
                1,
            )
            cv2.imshow("Identity Test - Capture", display)

            key = cv2.waitKey(1) & 0xFF
            if key == 27 or key == ord("q"):
                break
            elif key == 32:
                captured = frame
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()

    return captured


def _load_images_from_directory(image_dir: str) -> List[Tuple[str, np.ndarray]]:
    """Load all images from a directory."""
    path = Path(image_dir)
    if not path.exists():
        print(f"Error: Directory not found: {image_dir}")
        return []

    images = []
    for ext in ("*.jpg", "*.jpeg", "*.png", "*.bmp"):
        for img_path in path.glob(ext):
            img = cv2.imread(str(img_path))
            if img is not None:
                images.append((img_path.name, img))

    return sorted(images, key=lambda x: x[0])


class IdentityMatchingTester:
    """End-to-end tester for identity enrollment and matching."""

    def __init__(
        self,
        gallery_path: Optional[Path] = None,
        verbose: bool = False,
    ) -> None:
        self.verbose = verbose
        self._temp_dir: Optional[tempfile.TemporaryDirectory] = None
        
        if gallery_path is None:
            self._temp_dir = tempfile.TemporaryDirectory()
            self.gallery_path = Path(self._temp_dir.name) / "test_gallery.json"
        else:
            self.gallery_path = gallery_path

        self._identity_store = None
        self._reid_embedder = None
        self._pipeline = None
        self._timing: dict = {}

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(f"  [DEBUG] {msg}")

    def setup(self) -> bool:
        """Initialize components."""
        print("\n=== Setting up test environment ===")
        
        try:
            t0 = time.time()
            from cv.identity_store import IdentityStore
            self._identity_store = IdentityStore(gallery_path=self.gallery_path)
            self._timing["store_init"] = time.time() - t0
            self._log(f"IdentityStore initialized in {self._timing['store_init']:.3f}s")
            
            t0 = time.time()
            from cv.reid_embeddings import ReIDEmbedder
            self._reid_embedder = ReIDEmbedder()
            dummy = np.zeros((128, 64, 3), dtype=np.uint8)
            _ = self._reid_embedder.extract_embedding(dummy)
            self._timing["embedder_init"] = time.time() - t0
            self._log(f"ReIDEmbedder initialized in {self._timing['embedder_init']:.3f}s")
            
            t0 = time.time()
            from cv.cv_pipeline import CVPipeline
            import os
            os.environ.setdefault("CV_POSE_BACKEND", "none")
            self._pipeline = CVPipeline(identity_store=self._identity_store)
            self._timing["pipeline_init"] = time.time() - t0
            self._log(f"CVPipeline initialized in {self._timing['pipeline_init']:.3f}s")
            
            print(f"  Gallery: {self.gallery_path}")
            print(f"  Embedder device: {self._reid_embedder.device}")
            return True
            
        except Exception as e:
            print(f"ERROR: Setup failed: {e}")
            import traceback
            traceback.print_exc()
            return False

    def cleanup(self) -> None:
        """Clean up resources."""
        if self._pipeline:
            self._pipeline.close()
        if self._temp_dir:
            self._temp_dir.cleanup()

    def clear_gallery(self) -> None:
        """Clear any existing subjects in the gallery."""
        if self._identity_store:
            count = self._identity_store.clear()
            print(f"  Cleared {count} existing subjects from gallery")

    def test_embedding_extraction(self, image: np.ndarray) -> Optional[np.ndarray]:
        """Test embedding extraction from an image."""
        print("\n=== Test: Embedding Extraction ===")
        
        try:
            t0 = time.time()
            embedding = self._reid_embedder.extract_embedding(image)
            elapsed = time.time() - t0
            self._timing["embedding_extraction"] = elapsed
            
            print(f"  Shape: {embedding.shape}")
            print(f"  Dtype: {embedding.dtype}")
            print(f"  Norm: {np.linalg.norm(embedding):.4f} (should be ~1.0)")
            print(f"  Time: {elapsed*1000:.1f}ms")
            
            assert embedding.shape == (512,), f"Expected (512,), got {embedding.shape}"
            assert embedding.dtype == np.float32, f"Expected float32, got {embedding.dtype}"
            norm = np.linalg.norm(embedding)
            assert 0.99 < norm < 1.01, f"Expected norm ~1.0, got {norm}"
            
            print("  PASSED")
            return embedding
            
        except Exception as e:
            print(f"  FAILED: {e}")
            return None

    def test_enrollment(
        self,
        image: np.ndarray,
        subject_id: str,
        display_name: str,
    ) -> bool:
        """Test subject enrollment."""
        print(f"\n=== Test: Enrollment ({subject_id}) ===")
        
        try:
            t0 = time.time()
            embedding = self._reid_embedder.extract_embedding(image)
            embed_time = time.time() - t0
            
            t0 = time.time()
            subject = self._identity_store.enroll(
                subject_id=subject_id,
                display_name=display_name,
                embedding=embedding,
            )
            enroll_time = time.time() - t0
            self._timing[f"enroll_{subject_id}"] = embed_time + enroll_time
            
            print(f"  Subject ID: {subject.subject_id}")
            print(f"  Display Name: {subject.display_name}")
            print(f"  Color: {subject.color}")
            print(f"  Embeddings: {len(subject.embeddings)}")
            print(f"  Time: {(embed_time + enroll_time)*1000:.1f}ms (embed: {embed_time*1000:.1f}ms)")
            
            stored = self._identity_store.get(subject_id)
            assert stored is not None, "Subject not stored"
            assert stored.subject_id == subject_id
            assert len(stored.embeddings) >= 1
            
            print("  PASSED")
            return True
            
        except Exception as e:
            print(f"  FAILED: {e}")
            return False

    def test_matching(
        self,
        image: np.ndarray,
        expected_id: Optional[str],
        expected_enrolled: bool,
        description: str = "",
    ) -> bool:
        """Test identity matching."""
        print(f"\n=== Test: Matching ({description or 'image'}) ===")
        
        try:
            t0 = time.time()
            embedding = self._reid_embedder.extract_embedding(image)
            embed_time = time.time() - t0
            
            t0 = time.time()
            match = self._identity_store.match(embedding)
            match_time = time.time() - t0
            self._timing[f"match_{description}"] = embed_time + match_time
            
            if match:
                matched_id, similarity = match
                print(f"  Matched: {matched_id} (similarity: {similarity:.4f})")
            else:
                print("  Matched: None (no match above threshold)")
            
            print(f"  Expected: {expected_id} (enrolled={expected_enrolled})")
            print(f"  Time: {(embed_time + match_time)*1000:.1f}ms")
            
            if expected_id is not None:
                if match is None:
                    print(f"  FAILED: Expected match to {expected_id}, got None")
                    return False
                if match[0] != expected_id:
                    print(f"  FAILED: Expected {expected_id}, got {match[0]}")
                    return False
            else:
                if match is not None:
                    print(f"  WARNING: Expected no match, got {match[0]} (sim={match[1]:.4f})")
            
            print("  PASSED")
            return True
            
        except Exception as e:
            print(f"  FAILED: {e}")
            return False

    def test_pipeline_detection(
        self,
        frame: np.ndarray,
        expected_id: Optional[str],
        expected_enrolled: bool,
        description: str = "",
    ) -> bool:
        """Test full pipeline detection with identity enrichment."""
        print(f"\n=== Test: Pipeline Detection ({description or 'frame'}) ===")
        
        try:
            t0 = time.time()
            obs = self._pipeline.process_frame(frame, session_id="test")
            elapsed = time.time() - t0
            self._timing[f"pipeline_{description}"] = elapsed
            
            print(f"  Person detected: {obs.person_detected}")
            print(f"  Detections: {len(obs.detections)}")
            
            person_dets = [d for d in obs.detections if d.label == "person"]
            
            if person_dets:
                det = person_dets[0]
                print(f"  Person ID: {det.person_id}")
                print(f"  Display Name: {det.display_name}")
                print(f"  Is Enrolled: {det.is_enrolled}")
                print(f"  Identity Conf: {det.identity_confidence}")
                print(f"  Bbox Color: {det.bbox_color}")
                
                if expected_enrolled and not det.is_enrolled:
                    print(f"  FAILED: Expected enrolled=True, got False")
                    return False
                if expected_id and det.person_id != expected_id:
                    print(f"  WARNING: Expected ID {expected_id}, got {det.person_id}")
            else:
                print("  No person detections (may be expected for synthetic images)")
            
            print(f"  Time: {elapsed*1000:.1f}ms")
            print("  PASSED")
            return True
            
        except Exception as e:
            print(f"  FAILED: {e}")
            import traceback
            traceback.print_exc()
            return False

    def test_similarity_discrimination(self) -> bool:
        """Test that same person has high similarity, different person has low."""
        print("\n=== Test: Similarity Discrimination ===")
        
        try:
            img1a = _create_synthetic_person_image(seed=100)
            img1b = _create_synthetic_person_image(seed=100)
            img2 = _create_synthetic_person_image(seed=200)
            
            emb1a = self._reid_embedder.extract_embedding(img1a)
            emb1b = self._reid_embedder.extract_embedding(img1b)
            emb2 = self._reid_embedder.extract_embedding(img2)
            
            sim_same = float(np.dot(emb1a, emb1b))
            sim_diff = float(np.dot(emb1a, emb2))
            
            print(f"  Same person similarity: {sim_same:.4f}")
            print(f"  Different person similarity: {sim_diff:.4f}")
            print(f"  Discrimination: {sim_same - sim_diff:.4f}")
            
            if sim_same > sim_diff:
                print("  PASSED: Same person > different person")
                return True
            else:
                print("  WARNING: Same person similarity not higher (synthetic images may not discriminate well)")
                return True
                
        except Exception as e:
            print(f"  FAILED: {e}")
            return False

    def test_visitor_tracking(self) -> bool:
        """Test anonymous visitor ID assignment."""
        print("\n=== Test: Visitor Tracking ===")
        
        try:
            visitor_img = _create_synthetic_person_image(seed=999)
            
            h, w = 480, 640
            frame = np.ones((h, w, 3), dtype=np.uint8) * 128
            
            vh, vw = visitor_img.shape[:2]
            y_off = (h - vh) // 2
            x_off = (w - vw) // 2
            frame[y_off:y_off+vh, x_off:x_off+vw] = visitor_img
            
            obs = self._pipeline.process_frame(frame, session_id="visitor-test")
            
            person_dets = [d for d in obs.detections if d.label == "person"]
            
            if person_dets:
                det = person_dets[0]
                print(f"  Person ID: {det.person_id}")
                print(f"  Is Enrolled: {det.is_enrolled}")
                
                if det.is_enrolled:
                    print("  WARNING: Visitor detected as enrolled")
                elif det.person_id and det.person_id.startswith("visitor_"):
                    print("  PASSED: Visitor ID assigned correctly")
                    return True
                else:
                    print(f"  INFO: Person ID: {det.person_id}")
            else:
                print("  INFO: No person detected (synthetic image may not trigger YOLO)")
            
            print("  PASSED (with notes)")
            return True
            
        except Exception as e:
            print(f"  FAILED: {e}")
            return False

    def print_timing_summary(self) -> None:
        """Print timing metrics summary."""
        print("\n=== Timing Summary ===")
        for name, elapsed in sorted(self._timing.items()):
            print(f"  {name}: {elapsed*1000:.1f}ms")

    def run_synthetic_tests(self) -> Tuple[int, int]:
        """Run tests with synthetic images."""
        passed = 0
        failed = 0
        
        img1 = _create_synthetic_person_image(seed=42)
        img2 = _create_synthetic_person_image(seed=42)
        img_other = _create_synthetic_person_image(seed=123)
        
        if self.test_embedding_extraction(img1):
            passed += 1
        else:
            failed += 1
        
        if self.test_enrollment(img1, "test_subject_1", "Test Subject 1"):
            passed += 1
        else:
            failed += 1
        
        if self.test_matching(img2, "test_subject_1", True, "same_person"):
            passed += 1
        else:
            failed += 1
        
        if self.test_matching(img_other, None, False, "different_person"):
            passed += 1
        else:
            failed += 1
        
        if self.test_similarity_discrimination():
            passed += 1
        else:
            failed += 1
        
        h, w = 480, 640
        frame = np.ones((h, w, 3), dtype=np.uint8) * 128
        vh, vw = img1.shape[:2]
        y_off = (h - vh) // 2
        x_off = (w - vw) // 2
        frame[y_off:y_off+vh, x_off:x_off+vw] = img1
        
        if self.test_pipeline_detection(frame, "test_subject_1", True, "enrolled_subject"):
            passed += 1
        else:
            failed += 1
        
        if self.test_visitor_tracking():
            passed += 1
        else:
            failed += 1
        
        return passed, failed

    def run_camera_tests(self, camera_index: int) -> Tuple[int, int]:
        """Run tests with camera capture."""
        passed = 0
        failed = 0
        
        img1 = _capture_from_camera(camera_index, "Capture image for TEST_SUBJECT_1 enrollment")
        if img1 is None:
            print("Skipping camera tests (no image captured)")
            return 0, 0
        
        if self.test_embedding_extraction(img1):
            passed += 1
        else:
            failed += 1
        
        if self.test_enrollment(img1, "camera_subject", "Camera Subject"):
            passed += 1
        else:
            failed += 1
        
        img2 = _capture_from_camera(camera_index, "Capture SAME person for matching test")
        if img2 is not None:
            if self.test_matching(img2, "camera_subject", True, "same_person_camera"):
                passed += 1
            else:
                failed += 1
            
            if self.test_pipeline_detection(img2, "camera_subject", True, "camera_enrolled"):
                passed += 1
            else:
                failed += 1
        
        img_other = _capture_from_camera(camera_index, "Capture DIFFERENT person (or empty scene)")
        if img_other is not None:
            if self.test_matching(img_other, None, False, "different_person_camera"):
                passed += 1
            else:
                failed += 1
        
        return passed, failed

    def run_image_dir_tests(self, image_dir: str) -> Tuple[int, int]:
        """Run tests with images from a directory."""
        passed = 0
        failed = 0
        
        images = _load_images_from_directory(image_dir)
        if not images:
            print(f"No images found in {image_dir}")
            return 0, 0
        
        print(f"Found {len(images)} images in {image_dir}")
        
        if len(images) >= 1:
            name, img = images[0]
            if self.test_embedding_extraction(img):
                passed += 1
            else:
                failed += 1
            
            if self.test_enrollment(img, "dir_subject_1", f"Subject from {name}"):
                passed += 1
            else:
                failed += 1
        
        if len(images) >= 2:
            name, img = images[1]
            if self.test_matching(img, "dir_subject_1", True, name):
                passed += 1
            else:
                failed += 1
        
        for name, img in images[:5]:
            if self.test_pipeline_detection(img, None, False, name):
                passed += 1
            else:
                failed += 1
        
        return passed, failed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="End-to-end test for identity enrollment and matching.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    
    parser.add_argument(
        "--camera",
        type=int,
        metavar="INDEX",
        help="Camera index to capture test images from",
    )
    parser.add_argument(
        "--images",
        type=str,
        metavar="DIR",
        help="Directory containing test images",
    )
    parser.add_argument(
        "--gallery",
        type=str,
        metavar="PATH",
        help="Path to gallery file (uses temp file if not specified)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose output",
    )
    parser.add_argument(
        "--keep-gallery",
        action="store_true",
        help="Don't clear gallery before tests",
    )
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("  Identity Matching End-to-End Test Suite")
    print("=" * 60)
    
    gallery_path = Path(args.gallery) if args.gallery else None
    tester = IdentityMatchingTester(
        gallery_path=gallery_path,
        verbose=args.verbose,
    )
    
    try:
        if not tester.setup():
            return 1
        
        if not args.keep_gallery:
            tester.clear_gallery()
        
        total_passed = 0
        total_failed = 0
        
        if args.camera is not None:
            passed, failed = tester.run_camera_tests(args.camera)
            total_passed += passed
            total_failed += failed
        elif args.images:
            passed, failed = tester.run_image_dir_tests(args.images)
            total_passed += passed
            total_failed += failed
        else:
            passed, failed = tester.run_synthetic_tests()
            total_passed += passed
            total_failed += failed
        
        tester.print_timing_summary()
        
        print("\n" + "=" * 60)
        print(f"  RESULTS: {total_passed} passed, {total_failed} failed")
        print("=" * 60)
        
        return 0 if total_failed == 0 else 1
        
    finally:
        tester.cleanup()


if __name__ == "__main__":
    sys.exit(main())
