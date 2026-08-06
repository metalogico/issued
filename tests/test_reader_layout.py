from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_layout_preferences_are_persisted_and_validated():
    script = (PROJECT_ROOT / "reader" / "static" / "js" / "layout.js").read_text()

    assert "issued-layout-width" in script
    assert "issued-thumbnail-size" in script
    assert "issued-borderless-collage" in script
    assert "['fixed', 'full']" in script
    assert "['small', 'medium', 'large']" in script
    assert "localStorage.setItem" in script
    assert "aria-pressed" in script
    assert "aria-checked" in script


def test_layout_styles_support_full_width_and_resizable_cover_grids():
    styles = (PROJECT_ROOT / "reader" / "static" / "css" / "style.css").read_text()

    assert 'html[data-layout-width="full"] .layout-container' in styles
    assert 'html[data-thumbnail-size="small"] .cover-grid' in styles
    assert 'html[data-thumbnail-size="large"] .cover-grid' in styles
    assert 'html[data-borderless="true"] .cover-grid' in styles
    assert 'html[data-borderless="true"] .comic-card-details' in styles
    assert 'html[data-borderless="true"] .folder-card-details' in styles
    assert "--cover-min-width" in styles


def test_library_grids_opt_in_to_cover_sizing():
    folder_grid = (PROJECT_ROOT / "reader" / "templates" / "partials" / "folder-grid.html").read_text()
    comics_section = (PROJECT_ROOT / "reader" / "templates" / "partials" / "comics-section.html").read_text()

    assert "cover-grid" in folder_grid
    assert comics_section.count("cover-grid") == 2
