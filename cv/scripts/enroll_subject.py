#!/usr/bin/env python3
"""
CLI tool for enrolling subjects into the identity gallery.

Usage:
    # Enroll from camera (captures live frame)
    python -m cv.scripts.enroll_subject --camera 0 --id grandma --name "Grandma"

    # Enroll from image file
    python -m cv.scripts.enroll_subject --image /path/to/photo.jpg --id grandpa --name "Grandpa"

    # Add additional view to existing subject
    python -m cv.scripts.enroll_subject --camera 0 --id grandma --add-view

    # List enrolled subjects
    python -m cv.scripts.enroll_subject --list

    # Delete a subject
    python -m cv.scripts.enroll_subject --delete grandma

    # Enroll via running server (instead of direct local enrollment)
    python -m cv.scripts.enroll_subject --image photo.jpg --id grandma --name "Grandma" --server http://localhost:8080
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional


def _capture_from_camera(camera_index: int, show_crop: bool = True) -> Optional[bytes]:
    """
    Capture a frame from camera with interactive preview.
    
    Shows live preview and captures when user presses SPACE.
    Press ESC or Q to cancel.
    
    Args:
        camera_index: Camera device index
        show_crop: If True, show the detected person crop after capture
    
    Returns:
        JPEG-encoded image bytes, or None if cancelled.
    """
    import cv2
    
    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        print(f"Error: Cannot open camera {camera_index}")
        return None

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    print("\n=== Camera Capture ===")
    print("Press SPACE to capture")
    print("Press ESC or Q to cancel")
    print()

    captured_frame = None

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("Error: Failed to read frame from camera")
                break

            display = frame.copy()
            h, w = display.shape[:2]
            
            cv2.putText(
                display,
                "Press SPACE to capture | ESC/Q to cancel",
                (10, h - 20),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 0),
                2,
            )

            cv2.imshow("Enroll Subject - Press SPACE to capture", display)

            key = cv2.waitKey(1) & 0xFF

            if key == 27 or key == ord("q") or key == ord("Q"):
                print("Capture cancelled.")
                break
            elif key == 32:  # SPACE
                captured_frame = frame
                print("Frame captured!")
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()

    if captured_frame is None:
        return None

    # Show the captured frame with person detection
    if show_crop:
        _show_captured_person(captured_frame)

    success, encoded = cv2.imencode(".jpg", captured_frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
    if not success:
        print("Error: Failed to encode frame as JPEG")
        return None

    return encoded.tobytes()


def _show_captured_person(frame) -> None:
    """
    Display the captured frame with detected person highlighted.
    Shows for 3 seconds or until any key is pressed.
    """
    import cv2
    
    try:
        from ultralytics import YOLO
    except ImportError:
        print("(YOLO not available for preview)")
        return

    display = frame.copy()
    h, w = display.shape[:2]

    model = YOLO("yolov8n.pt")
    results = model.predict(source=frame, verbose=False)

    person_found = False
    if results and results[0].boxes is not None:
        boxes = results[0].boxes
        for i, cls in enumerate(boxes.cls.tolist()):
            if int(cls) == 0:  # person class
                person_found = True
                conf = boxes.conf[i].item()
                xyxy = boxes.xyxy[i].tolist()
                x1, y1, x2, y2 = map(int, xyxy)
                
                # Draw bounding box
                cv2.rectangle(display, (x1, y1), (x2, y2), (0, 255, 0), 3)
                
                # Draw label
                label = f"Person {conf:.0%}"
                (text_w, text_h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)
                cv2.rectangle(display, (x1, y1 - text_h - 10), (x1 + text_w + 4, y1), (0, 255, 0), -1)
                cv2.putText(display, label, (x1 + 2, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)

    # Add status text
    status = "Person detected - this will be enrolled" if person_found else "No person detected!"
    color = (0, 255, 0) if person_found else (0, 0, 255)
    cv2.putText(display, status, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2)
    cv2.putText(display, "Press any key to continue...", (10, h - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

    cv2.imshow("Captured Frame - Press any key", display)
    cv2.waitKey(3000)  # Show for 3 seconds or until key press
    cv2.destroyAllWindows()


def _load_image_file(image_path: str) -> Optional[bytes]:
    """Load an image file and return JPEG bytes."""
    import cv2
    
    path = Path(image_path)
    if not path.exists():
        print(f"Error: Image file not found: {image_path}")
        return None

    frame = cv2.imread(str(path))
    if frame is None:
        print(f"Error: Could not decode image: {image_path}")
        return None

    success, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
    if not success:
        print("Error: Failed to encode image as JPEG")
        return None

    return encoded.tobytes()


def _detect_person_in_image(image_bytes: bytes) -> bool:
    """Check if the image contains at least one person detection."""
    import cv2
    import numpy as np
    from ultralytics import YOLO
    
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if frame is None:
        return False

    model = YOLO("yolov8n.pt")
    results = model.predict(source=frame, verbose=False)
    
    if results and results[0].boxes is not None:
        for cls in results[0].boxes.cls.tolist():
            if int(cls) == 0:  # person class
                return True
    
    return False


def _enroll_local(
    image_bytes: bytes,
    subject_id: str,
    display_name: str,
    color: Optional[str],
    add_view: bool,
) -> bool:
    """Enroll directly using local IdentityStore."""
    import cv2
    import numpy as np
    
    from cv.identity_store import IdentityStore
    from cv.reid_embeddings import ReIDEmbedder

    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if frame is None:
        print("Error: Could not decode image")
        return False

    print("Extracting embedding (this may take a moment on first run)...")
    embedder = ReIDEmbedder()
    embedding = embedder.extract_embedding(frame)

    store = IdentityStore()

    if add_view:
        if store.get(subject_id) is None:
            print(f"Error: Subject '{subject_id}' not found. Use --id and --name to enroll first.")
            return False
        
        store.add_embedding(subject_id, embedding)
        subject = store.get(subject_id)
        print(f"\nAdded view for subject '{subject_id}'")
        if subject:
            print(f"  Total embeddings: {len(subject.embeddings)}")
    else:
        subject = store.enroll(
            subject_id=subject_id,
            display_name=display_name,
            embedding=embedding,
            color=color,
        )
        print(f"\nEnrolled subject '{display_name}' (id: {subject_id})")
        print(f"  Color: {subject.color}")
        print(f"  Total embeddings: {len(subject.embeddings)}")
        print(f"  Gallery: {store.gallery_path}")

    return True


def _enroll_via_server(
    image_bytes: bytes,
    subject_id: str,
    display_name: str,
    color: Optional[str],
    add_view: bool,
    server_url: str,
) -> bool:
    """Enroll via HTTP API to running CV server."""
    try:
        import httpx
    except ImportError:
        print("Error: httpx is required for server mode. Install with: pip install httpx")
        return False

    if add_view:
        url = f"{server_url.rstrip('/')}/subjects/{subject_id}/add-view"
        files = {"file": ("image.jpg", image_bytes, "image/jpeg")}
        data = {}
    else:
        url = f"{server_url.rstrip('/')}/enroll-subject"
        files = {"file": ("image.jpg", image_bytes, "image/jpeg")}
        data = {
            "subject_id": subject_id,
            "display_name": display_name,
        }
        if color:
            data["color"] = color

    print(f"Sending to {url}...")

    try:
        with httpx.Client(timeout=60.0) as client:
            response = client.post(url, files=files, data=data)

        if response.status_code == 200:
            result = response.json()
            print(f"\nSuccess: {result.get('message', 'Enrolled successfully')}")
            print(f"  Subject ID: {result.get('subject_id')}")
            print(f"  Embeddings: {result.get('embedding_count')}")
            return True
        else:
            print(f"\nError: Server returned {response.status_code}")
            try:
                error = response.json()
                print(f"  Detail: {error.get('detail', response.text)}")
            except Exception:
                print(f"  Response: {response.text}")
            return False

    except httpx.ConnectError:
        print(f"\nError: Could not connect to {server_url}")
        print("Make sure the CV server is running.")
        return False
    except Exception as e:
        print(f"\nError: {e}")
        return False


def _list_subjects_local() -> None:
    """List all enrolled subjects from local gallery."""
    from cv.identity_store import IdentityStore

    store = IdentityStore()
    subjects = store.list_subjects()

    if not subjects:
        print("\nNo subjects enrolled.")
        print(f"Gallery: {store.gallery_path}")
        return

    print(f"\n=== Enrolled Subjects ({len(subjects)}) ===")
    print(f"Gallery: {store.gallery_path}\n")

    for s in subjects:
        print(f"  {s['subject_id']}:")
        print(f"    Display Name: {s['display_name']}")
        print(f"    Color: {s['color']}")
        print(f"    Embeddings: {s['embedding_count']}")
        print(f"    Enrolled: {s['enrolled_at']}")
        print()


def _list_subjects_server(server_url: str) -> None:
    """List enrolled subjects via HTTP API."""
    try:
        import httpx
    except ImportError:
        print("Error: httpx is required for server mode. Install with: pip install httpx")
        return

    url = f"{server_url.rstrip('/')}/subjects"

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(url)

        if response.status_code == 200:
            result = response.json()
            subjects = result.get("subjects", [])

            if not subjects:
                print("\nNo subjects enrolled.")
                return

            print(f"\n=== Enrolled Subjects ({len(subjects)}) ===\n")

            for s in subjects:
                print(f"  {s['subject_id']}:")
                print(f"    Display Name: {s['display_name']}")
                print(f"    Color: {s['color']}")
                print(f"    Embeddings: {s['embedding_count']}")
                print(f"    Enrolled: {s['enrolled_at']}")
                print()
        else:
            print(f"\nError: Server returned {response.status_code}")

    except httpx.ConnectError:
        print(f"\nError: Could not connect to {server_url}")
    except Exception as e:
        print(f"\nError: {e}")


def _delete_subject_local(subject_id: str) -> bool:
    """Delete a subject from local gallery."""
    from cv.identity_store import IdentityStore

    store = IdentityStore()
    
    if store.delete(subject_id):
        print(f"\nDeleted subject '{subject_id}'")
        return True
    else:
        print(f"\nError: Subject '{subject_id}' not found")
        return False


def _delete_subject_server(subject_id: str, server_url: str) -> bool:
    """Delete a subject via HTTP API."""
    try:
        import httpx
    except ImportError:
        print("Error: httpx is required for server mode. Install with: pip install httpx")
        return False

    url = f"{server_url.rstrip('/')}/subjects/{subject_id}"

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.delete(url)

        if response.status_code == 200:
            print(f"\nDeleted subject '{subject_id}'")
            return True
        elif response.status_code == 404:
            print(f"\nError: Subject '{subject_id}' not found")
            return False
        else:
            print(f"\nError: Server returned {response.status_code}")
            return False

    except httpx.ConnectError:
        print(f"\nError: Could not connect to {server_url}")
        return False
    except Exception as e:
        print(f"\nError: {e}")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Enroll subjects into the identity gallery for person tracking.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument(
        "--camera",
        type=int,
        metavar="INDEX",
        help="Camera index to capture from (e.g., 0)",
    )
    source_group.add_argument(
        "--image",
        type=str,
        metavar="PATH",
        help="Path to image file to enroll from",
    )
    source_group.add_argument(
        "--list",
        action="store_true",
        help="List all enrolled subjects",
    )
    source_group.add_argument(
        "--delete",
        type=str,
        metavar="SUBJECT_ID",
        help="Delete an enrolled subject",
    )

    parser.add_argument(
        "--id",
        type=str,
        dest="subject_id",
        help="Subject ID (e.g., 'grandma', 'grandpa')",
    )
    parser.add_argument(
        "--name",
        type=str,
        dest="display_name",
        help="Display name (e.g., 'Grandma', 'Grandpa')",
    )
    parser.add_argument(
        "--color",
        type=str,
        help="Hex color for bounding box (e.g., '#FF6B6B')",
    )
    parser.add_argument(
        "--add-view",
        action="store_true",
        help="Add additional embedding view to existing subject",
    )
    parser.add_argument(
        "--server",
        type=str,
        metavar="URL",
        help="CV server URL for remote enrollment (e.g., http://localhost:8080)",
    )
    parser.add_argument(
        "--skip-person-check",
        action="store_true",
        help="Skip person detection validation",
    )

    args = parser.parse_args()

    # Handle --list
    if args.list:
        if args.server:
            _list_subjects_server(args.server)
        else:
            _list_subjects_local()
        return 0

    # Handle --delete
    if args.delete:
        if args.server:
            success = _delete_subject_server(args.delete, args.server)
        else:
            success = _delete_subject_local(args.delete)
        return 0 if success else 1

    # For enrollment, we need either --camera or --image
    if args.camera is None and args.image is None:
        parser.print_help()
        print("\nError: Must specify --camera, --image, --list, or --delete")
        return 1

    # Validate subject_id for enrollment
    if not args.add_view:
        if not args.subject_id:
            print("Error: --id is required for enrollment")
            return 1
        if not args.display_name:
            print("Error: --name is required for enrollment")
            return 1
    else:
        if not args.subject_id:
            print("Error: --id is required with --add-view")
            return 1

    # Get image bytes
    if args.camera is not None:
        print(f"Opening camera {args.camera}...")
        image_bytes = _capture_from_camera(args.camera)
    else:
        print(f"Loading image: {args.image}")
        image_bytes = _load_image_file(args.image)

    if image_bytes is None:
        return 1

    # Validate person in image
    if not args.skip_person_check:
        print("Checking for person in image...")
        if not _detect_person_in_image(image_bytes):
            print("\nWarning: No person detected in image!")
            print("For best results, ensure the person is clearly visible.")
            print("Use --skip-person-check to bypass this validation.")
            response = input("Continue anyway? [y/N]: ").strip().lower()
            if response not in ("y", "yes"):
                print("Enrollment cancelled.")
                return 1

    # Enroll
    if args.server:
        success = _enroll_via_server(
            image_bytes=image_bytes,
            subject_id=args.subject_id or "",
            display_name=args.display_name or "",
            color=args.color,
            add_view=args.add_view,
            server_url=args.server,
        )
    else:
        success = _enroll_local(
            image_bytes=image_bytes,
            subject_id=args.subject_id or "",
            display_name=args.display_name or "",
            color=args.color,
            add_view=args.add_view,
        )

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
