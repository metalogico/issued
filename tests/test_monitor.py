"""Tests for filesystem monitoring."""

import time
from pathlib import Path

import pytest

from server.monitor import ComicLibraryHandler, MonitorTask, optimize_tasks


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

