"""reader.repo – feature-domain repository sub-package.

Re-exports every public function so existing callers continue to work unchanged.
"""

from .folders import (
    get_top_folders,
    add_folder_item_counts,
    get_folder,
    get_subfolders_with_item_count,
    get_breadcrumbs_for_folder,
    get_folder_preview_thumbnails,
)
from .comics import (
    get_comics_in_folder,
    get_last_added_comics,
    get_continue_reading_comics,
    search_comics,
    search_comics_grouped,
)
from .metadata import (
    get_comic_id_by_uuid,
    get_folder_id_for_comic,
    get_initial_page,
    get_metadata,
    ensure_metadata_row,
    update_metadata,
)
from .progress import (
    get_progress,
    update_progress,
    clear_progress,
    mark_all_comics_in_folder_completed,
    toggle_comic_completed,
)
from .tags import (
    get_tags_for_comic,
    get_all_tags,
    get_all_tags_with_counts,
    get_comics_for_tag,
    delete_tag,
    set_tags_for_comic,
)
from .ongoing import (
    folder_is_leaf,
    folder_comic_count,
    is_ongoing_series,
    set_ongoing_series,
    list_ongoing_series_rows,
)

__all__ = [
    "get_top_folders", "add_folder_item_counts", "get_folder",
    "get_subfolders_with_item_count", "get_breadcrumbs_for_folder",
    "get_folder_preview_thumbnails",
    "get_comics_in_folder", "get_last_added_comics", "get_continue_reading_comics",
    "search_comics", "search_comics_grouped",
    "get_comic_id_by_uuid", "get_folder_id_for_comic", "get_initial_page",
    "get_metadata", "ensure_metadata_row", "update_metadata",
    "get_progress", "update_progress", "clear_progress",
    "mark_all_comics_in_folder_completed", "toggle_comic_completed",
    "get_tags_for_comic", "get_all_tags", "get_all_tags_with_counts",
    "get_comics_for_tag", "delete_tag", "set_tags_for_comic",
    "folder_is_leaf", "folder_comic_count", "is_ongoing_series",
    "set_ongoing_series", "list_ongoing_series_rows",
]
