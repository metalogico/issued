"""Filesystem monitoring for Issued.

Uses Watchdog to detect new/modified/deleted comics in real-time
and automatically update the database.
"""

from __future__ import annotations

import time
import queue
from pathlib import Path
from threading import Thread, Event
from typing import Optional, Dict, Any, NamedTuple

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent

from .config import IssuedConfig
from .logging_config import get_logger
from .scanner import is_comic_file, scan_folder, scan_file, delete_path, move_path

logger = get_logger(__name__)


class MonitorTask(NamedTuple):
    action: str
    path: Path
    dest_path: Optional[Path] = None


class ComicLibraryHandler(FileSystemEventHandler):
    """Handle filesystem events and push them to a processing queue."""

    def __init__(self, task_queue: queue.Queue, debounce_seconds: int = 2):
        super().__init__()
        self.task_queue = task_queue
        self.debounce_seconds = debounce_seconds
        self._last_modified: Dict[str, float] = {}

    def on_created(self, event: FileSystemEvent) -> None:
        path = Path(event.src_path)
        if path.name.startswith("._"):
            return

        if event.is_directory:
            self.task_queue.put(MonitorTask("scan_folder", path))
        elif is_comic_file(path):
            self.task_queue.put(MonitorTask("scan_file", path))

    def on_deleted(self, event: FileSystemEvent) -> None:
        path = Path(event.src_path)
        if path.name.startswith("._"):
            return
            
        self.task_queue.put(MonitorTask("delete", path))

    def on_moved(self, event: FileSystemEvent) -> None:
        src_path = Path(event.src_path)
        dest_path = Path(event.dest_path)
        
        if src_path.name.startswith("._") or dest_path.name.startswith("._"):
            return

        self.task_queue.put(MonitorTask("move", src_path, dest_path=dest_path))

    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return

        path = Path(event.src_path)
        if path.name.startswith("._") or not is_comic_file(path):
            return

        # Simple debounce for modified files
        now = time.time()
        key = str(path)
        last = self._last_modified.get(key, 0)
        if now - last < self.debounce_seconds:
            return
        
        self._last_modified[key] = now
        self.task_queue.put(MonitorTask("scan_file", path))

        # Prune stale entries to prevent unbounded growth
        cutoff = now - self.debounce_seconds * 2
        self._last_modified = {
            k: v for k, v in self._last_modified.items() if v > cutoff
        }


def optimize_tasks(tasks: list[MonitorTask]) -> list[MonitorTask]:
    """Deduplicate and optimize a batch of tasks.
    
    Rules:
    1. If scanning a folder, ignore scans for its subfolders and files.
    2. If deleting a folder, ignore deletes for its subfolders/files.
    3. Keep moves as is (usually unique per file/folder).
    """
    if not tasks:
        return []

    # Separate tasks by type
    scan_folders = {t.path: t for t in tasks if t.action == "scan_folder"}
    scan_files = {t.path: t for t in tasks if t.action == "scan_file"}
    deletes = {t.path: t for t in tasks if t.action == "delete"}
    moves = [t for t in tasks if t.action == "move"]

    # Optimize folder scans: remove subfolders if parent is scanned
    # Sort by path length so we process parents first
    sorted_folder_paths = sorted(scan_folders.keys())
    final_scan_folders = {}
    
    for path in sorted_folder_paths:
        # Check if any parent of 'path' is already in final_scan_folders
        is_subfolder = False
        for parent in final_scan_folders:
            if path != parent and path.is_relative_to(parent):
                is_subfolder = True
                break
        
        if not is_subfolder:
            final_scan_folders[path] = scan_folders[path]

    # Optimize file scans: remove if inside a scanned folder
    final_scan_files = []
    for path, task in scan_files.items():
        is_covered = False
        for folder_path in final_scan_folders:
            if path.is_relative_to(folder_path):
                is_covered = True
                break
        if not is_covered:
            final_scan_files.append(task)

    # Optimize deletes: remove sub-paths if parent is deleted
    sorted_delete_paths = sorted(deletes.keys())
    final_deletes = {}
    
    for path in sorted_delete_paths:
        is_subitem = False
        for parent in final_deletes:
            if path != parent and path.is_relative_to(parent):
                is_subitem = True
                break
        
        if not is_subitem:
            final_deletes[path] = deletes[path]

    # Reassemble tasks in a logical order:
    # 1. Deletes (cleanup first)
    # 2. Moves
    # 3. Folder Scans (top-down)
    # 4. File Scans
    
    optimized = []
    optimized.extend(final_deletes.values())
    optimized.extend(moves)
    # Sort folder scans to ensure top-down processing order
    optimized.extend(sorted(final_scan_folders.values(), key=lambda t: t.path))
    optimized.extend(final_scan_files)
    
    return optimized


def process_queue(task_queue: queue.Queue, config: IssuedConfig, stop_event: Event) -> None:
    """Worker function to process filesystem events sequentially with batching."""
    BATCH_WINDOW = 1.0  # Seconds to wait for more events
    
    while not stop_event.is_set():
        try:
            # Block until first task arrives
            first_task = task_queue.get(timeout=1.0)
        except queue.Empty:
            continue

        # Start accumulating a batch
        batch = [first_task]
        start_time = time.time()
        
        while (time.time() - start_time) < BATCH_WINDOW:
            try:
                # Non-blocking get to drain queue
                task = task_queue.get_nowait()
                batch.append(task)
            except queue.Empty:
                # Queue empty, wait a bit to see if more come (debounce burst)
                time.sleep(0.1)
                continue
        
        optimized_tasks = optimize_tasks(batch)
        for _ in range(len(batch)):
            try:
                task_queue.task_done()
            except ValueError:
                pass # Ignore if called too many times

        for task in optimized_tasks:
            try:
                if task.action == "scan_folder":
                    scan_folder(task.path, config)
                elif task.action == "scan_file":
                    scan_file(task.path, config)
                elif task.action == "delete":
                    delete_path(task.path, config)
                elif task.action == "move":
                    if task.dest_path:
                        move_path(task.path, task.dest_path, config)
            except Exception as e:
                logger.error(f"Error processing task {task}: {e}")



def start_file_monitoring(config: IssuedConfig) -> Optional[Observer]:
    """Start filesystem monitoring if enabled in config."""
    if not config.monitoring.enabled:
        return None

    library_path = config.library_path
    if not library_path.exists():
        logger.error(f"Library path does not exist: {library_path}")
        return None

    task_queue: queue.Queue = queue.Queue()
    stop_event = Event()

    # Start the worker thread
    worker = Thread(
        target=process_queue, 
        args=(task_queue, config, stop_event), 
        daemon=True,
        name="IssuedMonitorWorker"
    )
    worker.start()

    debounce = config.monitoring.debounce_seconds
    event_handler = ComicLibraryHandler(task_queue, debounce)
    
    observer = Observer()
    observer.schedule(event_handler, str(library_path), recursive=True)
    observer.start()

    return observer
