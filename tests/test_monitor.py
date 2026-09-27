"""Tests for filesystem monitoring."""

import queue
import time
from pathlib import Path
from threading import Event, Thread

from server.config import (
    IssuedConfig,
    LibraryConfig,
    MonitoringConfig,
    ReaderAuthConfig,
    ScannerConfig,
    ServerConfig,
    ThumbnailConfig,
)
from server.monitor import ComicLibraryHandler, MonitorTask, optimize_tasks, process_queue
from server import monitor


def _make_config(library_path: Path) -> IssuedConfig:
    return IssuedConfig(
        library=LibraryConfig(path=library_path, name="Test Library"),
        server=ServerConfig(),
        thumbnails=ThumbnailConfig(),
        scanner=ScannerConfig(),
        monitoring=MonitoringConfig(enabled=False),
        reader_auth=ReaderAuthConfig(),
    )


def test_optimize_tasks_deduplicates():
    """Test that optimize_tasks removes duplicate operations."""
    tasks = [
        MonitorTask("scan_file", Path("/comics/issue1.cbz")),
        MonitorTask("scan_file", Path("/comics/issue1.cbz")),
        MonitorTask("scan_file", Path("/comics/issue2.cbz")),
    ]
    optimized = optimize_tasks(tasks)
    assert len(optimized) == 2
    assert MonitorTask("scan_file", Path("/comics/issue1.cbz")) in optimized
    assert MonitorTask("scan_file", Path("/comics/issue2.cbz")) in optimized


def test_optimize_tasks_keeps_different_actions():
    """Test that different actions on the same path are kept."""
    tasks = [
        MonitorTask("scan_file", Path("/comics/issue1.cbz")),
        MonitorTask("move", Path("/comics/issue1.cbz"), Path("/comics/moved.cbz")),
    ]
    optimized = optimize_tasks(tasks)
    # Both actions are kept since they're different
    assert len(optimized) == 2


def test_optimize_tasks_keeps_all_different_actions():
    """Test that all different action types are kept."""
    tasks = [
        MonitorTask("scan_file", Path("/comics/issue1.cbz")),
        MonitorTask("move", Path("/comics/issue1.cbz"), Path("/comics/moved.cbz")),
        MonitorTask("delete", Path("/comics/issue1.cbz")),
    ]
    optimized = optimize_tasks(tasks)
    # All different actions are kept
    assert len(optimized) == 3


def test_handler_ignores_macos_temp_files():
    """Test that handler ignores macOS temporary files (._*)."""
    import queue
    from unittest.mock import Mock
    
    task_queue = queue.Queue()
    handler = ComicLibraryHandler(task_queue, debounce_seconds=0)
    
    # Create mock event for macOS temp file
    event = Mock()
    event.src_path = "/comics/._issue1.cbz"
    event.is_directory = False
    
    handler.on_created(event)
    
    # Queue should be empty (file ignored)
    assert task_queue.empty()


def test_handler_queues_comic_file_creation():
    """Test that handler queues comic file creation events."""
    import queue
    from unittest.mock import Mock
    
    task_queue = queue.Queue()
    handler = ComicLibraryHandler(task_queue, debounce_seconds=0)
    
    # Create mock event for comic file
    event = Mock()
    event.src_path = "/comics/issue1.cbz"
    event.is_directory = False
    
    handler.on_created(event)
    
    # Queue should have one task
    assert not task_queue.empty()
    task = task_queue.get()
    assert task.action == "scan_file"
    assert task.path == Path("/comics/issue1.cbz")


def test_handler_queues_folder_creation():
    """Test that handler queues folder creation events."""
    import queue
    from unittest.mock import Mock
    
    task_queue = queue.Queue()
    handler = ComicLibraryHandler(task_queue, debounce_seconds=0)
    
    # Create mock event for folder
    event = Mock()
    event.src_path = "/comics/Marvel"
    event.is_directory = True
    
    handler.on_created(event)
    
    # Queue should have one task
    assert not task_queue.empty()
    task = task_queue.get()
    assert task.action == "scan_folder"
    assert task.path == Path("/comics/Marvel")


def test_process_queue_skips_deletes_when_library_not_ready(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "MONITOR_BATCH_WINDOW", 0)
    monkeypatch.setattr(monitor, "library_is_ready", lambda cfg: False)
    deleted = []
    monkeypatch.setattr(monitor, "delete_path", lambda path, cfg: deleted.append(path))
    scanned = []
    monkeypatch.setattr(monitor, "scan_library", lambda cfg: scanned.append("scan"))

    task_queue = queue.Queue()
    stop_event = Event()
    task_queue.put(MonitorTask("delete", tmp_path / "issue1.cbz"))

    thread = Thread(
        target=process_queue,
        args=(task_queue, _make_config(tmp_path), stop_event),
        daemon=True,
    )
    thread.start()
    time.sleep(0.2)
    stop_event.set()
    thread.join(timeout=2)

    assert deleted == []
    assert scanned == []


def test_process_queue_rescans_when_mount_returns(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "MONITOR_BATCH_WINDOW", 0)
    state = {"ready": False}
    monkeypatch.setattr(monitor, "library_is_ready", lambda cfg: state["ready"])
    deleted = []
    monkeypatch.setattr(monitor, "delete_path", lambda path, cfg: deleted.append(path))
    scanned = []
    monkeypatch.setattr(monitor, "scan_library", lambda cfg: scanned.append("scan"))

    task_queue = queue.Queue()
    stop_event = Event()
    task_queue.put(MonitorTask("delete", tmp_path / "issue1.cbz"))

    thread = Thread(
        target=process_queue,
        args=(task_queue, _make_config(tmp_path), stop_event),
        daemon=True,
    )
    thread.start()
    time.sleep(0.2)
    state["ready"] = True
    task_queue.put(MonitorTask("delete", tmp_path / "issue2.cbz"))
    time.sleep(0.2)
    stop_event.set()
    thread.join(timeout=2)

    assert deleted == []
    assert scanned == ["scan"]


