from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_reader_loads_zoom_interactions_as_a_native_module():
    template = (PROJECT_ROOT / "reader" / "templates" / "reader.html").read_text()
    entrypoint = (PROJECT_ROOT / "reader" / "static" / "js" / "reader.js").read_text()

    assert 'type="module"' in template
    assert "createReaderInteractions" in entrypoint
    assert "toggleZoomAtCenter" in entrypoint
    assert "resetZoom({ animate: false })" in entrypoint
    assert "z: () => interactions?.toggleZoomAtCenter()" in entrypoint


def test_reader_interactions_define_reduced_edges_and_double_tap_zoom():
    script = (PROJECT_ROOT / "reader" / "static" / "js" / "reader-interactions.js").read_text()

    assert "NAV_EDGE_RATIO = 0.18" in script
    assert "NAV_EDGE_MIN_PX = 64" in script
    assert "NAV_EDGE_MAX_PX = 160" in script
    assert "DOUBLE_TAP_MS = 300" in script
    assert "DOUBLE_TAP_DISTANCE_PX = 40" in script
    assert "PAN_THRESHOLD_PX = 6" in script
    assert "ZOOM_SCALE = 2" in script
    assert "MOBILE_SPREAD_ZOOM_SCALE = 3" in script
    assert "MOBILE_READER_MEDIA_QUERY = '(max-width: 639px)'" in script
    assert "mobileReader.matches && content.classList.contains('spread-mode')" in script
    assert "const innerBounds" in script
    assert "const axisCorrection" in script
    assert "const constrainSpreadPan" in script
    assert "bounds.bottom" in script
    assert "visualDeltaY / scale" in script
    assert "contain: value && !customContainment ? 'outside' : false" in script
    assert "constrainSpreadPan({ animate: true })" in script
    assert "content.addEventListener('panzoomend', panEnd)" in script
    assert "content.addEventListener('panzoompan', constrainSpreadPan)" not in script
    assert "clientY\n        - bounds.top" in script
    assert "disableZoom: true" in script
    assert "panOnlyWhenZoomed: true" in script
    assert "onPrevious()" in script
    assert "onNext()" in script


def test_panzoom_is_vendored_with_version_and_license():
    vendor_dir = PROJECT_ROOT / "reader" / "static" / "js" / "vendor"
    panzoom = (vendor_dir / "panzoom-4.6.2.es.min.js").read_text()
    license_text = (vendor_dir / "PANZOOM-LICENSE.txt").read_text()

    assert "Panzoom 4.6.2" in panzoom
    assert "export default globalThis.Panzoom" in panzoom
    assert "Copyright 2016-2019 Timmy Willison" in license_text
    assert "Permission is hereby granted" in license_text


def test_reader_styles_cover_zoom_pan_and_reduced_motion():
    styles = (PROJECT_ROOT / "reader" / "static" / "css" / "style.css").read_text()
    template = (PROJECT_ROOT / "reader" / "templates" / "reader.html").read_text()

    assert ".reader-image-wrap.is-zoomed" in styles
    assert ".reader-image-wrap.is-panning" in styles
    assert "transition: none !important" in styles
    assert 'data-zoomed="false"' in template
    assert "double-tap to zoom" in template


def test_reader_mobile_toolbar_reuses_actions_and_has_accessible_navigation():
    base = (PROJECT_ROOT / "reader" / "templates" / "base.html").read_text()
    template = (PROJECT_ROOT / "reader" / "templates" / "reader.html").read_text()

    assert "{% block body_class %}" in base
    assert 'class="site-header ' in base
    assert 'class="site-main ' in base
    assert "{% block body_class %}reader-page{% endblock %}" in template
    assert "folder_id=breadcrumbs[-1].id" in template
    assert "url_path(request, 'browse_root')" in template
    assert 'id="reader-actions-toggle"' in template
    assert 'role="group" aria-label="Reader actions"' in template
    assert 'aria-controls="reader-actions-panel"' in template
    assert 'aria-expanded="false"' in template
    assert template.count('id="reader-tags-wrap"') == 1
    assert template.count('id="btn-spread"') == 1
    assert template.count('id="btn-cover-sep"') == 1
    assert "Tap edges to turn · Double-tap to zoom" in template


def test_reader_mobile_styles_are_scoped_and_edge_to_edge():
    styles = (PROJECT_ROOT / "reader" / "static" / "css" / "style.css").read_text()

    assert "@media (max-width: 639px)" in styles
    assert ".reader-page .site-header" in styles
    assert ".reader-page .site-main" in styles
    assert ".reader-page .reader-image-wrap" in styles
    assert "width: fit-content" in styles
    assert "height: fit-content" in styles
    assert ".reader-controls.mobile-actions-open .reader-secondary-actions" in styles
    assert ".reader-page .reader-nav-btn" in styles
    assert "max-width: 48px !important" in styles
    assert "padding: 0 !important" in styles
    assert "border-radius: 0 !important" in styles
    assert 'html[data-theme="dark"] .reader-page .reader-controls' in styles


def test_reader_mobile_menu_manages_focus_escape_and_layout_changes():
    entrypoint = (PROJECT_ROOT / "reader" / "static" / "js" / "reader.js").read_text()

    assert "MOBILE_READER_MEDIA_QUERY" in entrypoint
    assert "window.matchMedia(MOBILE_READER_MEDIA_QUERY)" in entrypoint
    assert "setMobileActionsOpen" in entrypoint
    assert "actionsPanel.inert = !mobileActionsOpen" in entrypoint
    assert "actionsToggle?.setAttribute('aria-expanded'" in entrypoint
    assert "e.key === 'Escape' && mobileActionsOpen" in entrypoint
    assert "opening && event.detail === 0" in entrypoint
    assert "mobileReaderQuery.addEventListener('change', syncMobileActionsLayout)" in entrypoint
    assert "closeMobileActions(true)" in entrypoint
