import json
from pathlib import Path
import shutil
import subprocess

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SIZING_MODULE = PROJECT_ROOT / "reader" / "static" / "js" / "reader-sizing.js"


@pytest.fixture(scope="module")
def size_pages():
    node = shutil.which("node")
    if node is None:
        installed = sorted((Path.home() / ".nvm" / "versions" / "node").glob("*/bin/node"))
        node = str(installed[-1]) if installed else None
    if node is None:
        pytest.skip("Node.js is required to exercise the reader sizing module")

    script = """
      import { readFileSync } from 'node:fs';
      const source = readFileSync(process.argv[1], 'utf8');
      const moduleUrl = 'data:text/javascript;base64,' + Buffer.from(source).toString('base64');
      const { calculatePageSizing } = await import(moduleUrl);
      const args = JSON.parse(process.argv[2]);
      console.log(JSON.stringify(calculatePageSizing(...args)));
    """

    def calculate(*args):
        result = subprocess.run(
            [node, "--input-type=module", "-e", script, str(SIZING_MODULE), json.dumps(args)],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        return json.loads(result.stdout)

    return calculate


def test_fit_width_fills_width_and_keeps_the_whole_tall_page_scrollable(size_pages):
    [page] = size_pages(1200, 800, [{"width": 1000, "height": 1600}], "width")

    assert page["width"] == pytest.approx(1200)
    assert page["height"] == pytest.approx(1920)


def test_fit_height_fills_height_even_when_a_landscape_page_overflows_horizontally(size_pages):
    [page] = size_pages(1200, 800, [{"width": 1800, "height": 900}], "height")

    assert page["height"] == pytest.approx(800)
    assert page["width"] == pytest.approx(1600)


@pytest.mark.parametrize(
    ("original", "expected"),
    [
        ({"width": 1000, "height": 1600}, {"width": 500, "height": 800}),
        ({"width": 1800, "height": 900}, {"width": 1600, "height": 800}),
        ({"width": 100, "height": 200}, {"width": 400, "height": 800}),
    ],
    ids=["portrait", "landscape", "small-images-enlarge"],
)
def test_fit_height_uses_available_height_and_can_enlarge_small_pages(size_pages, original, expected):
    [page] = size_pages(1200, 800, [original], "height")

    assert page == pytest.approx(expected)


def test_fit_width_fits_both_pages_and_the_gap_with_a_common_height(size_pages):
    left, right = size_pages(
        1200,
        900,
        [{"width": 800, "height": 1200}, {"width": 1200, "height": 1200}],
        "width",
        4,
    )

    assert left == pytest.approx({"width": 478.4, "height": 717.6})
    assert right == pytest.approx({"width": 717.6, "height": 717.6})
    assert left["width"] + right["width"] + 4 == pytest.approx(1200)


def test_fit_height_can_display_a_wide_spread_larger_than_the_viewport(size_pages):
    left, right = size_pages(
        1200,
        900,
        [{"width": 800, "height": 1200}, {"width": 1200, "height": 1200}],
        "height",
        4,
    )

    assert left == pytest.approx({"width": 600, "height": 900})
    assert right == pytest.approx({"width": 900, "height": 900})
    assert left["width"] + right["width"] + 4 > 1200


@pytest.mark.parametrize("mode", ["width", "height"])
def test_every_mode_preserves_each_page_aspect_ratio_in_a_mixed_spread(size_pages, mode):
    originals = [{"width": 750, "height": 1000}, {"width": 1100, "height": 1700}]
    pages = size_pages(987, 654, originals, mode, 7)

    for original, page in zip(originals, pages, strict=True):
        assert page["width"] / page["height"] == pytest.approx(original["width"] / original["height"])
    assert pages[0]["height"] == pytest.approx(pages[1]["height"])
    if mode == "width":
        assert sum(page["width"] for page in pages) + 7 == pytest.approx(987)
    else:
        assert pages[0]["height"] == pytest.approx(654)


def test_default_unknown_and_removed_modes_fit_height(size_pages):
    args = [1200, 800, [{"width": 1800, "height": 900}]]

    assert size_pages(*args) == size_pages(*args, "height")
    assert size_pages(*args, "unknown") == size_pages(*args, "height")
    assert size_pages(*args, "screen") == size_pages(*args, "height")


@pytest.mark.parametrize(
    ("mode", "portrait_size", "landscape_size"),
    [
        ("width", {"width": 800, "height": 1280}, {"width": 1200, "height": 1920}),
        ("height", {"width": 750, "height": 1200}, {"width": 500, "height": 800}),
    ],
)
def test_sizing_recalculates_for_portrait_and_landscape_viewports(size_pages, mode, portrait_size, landscape_size):
    originals = [{"width": 1000, "height": 1600}]
    [portrait] = size_pages(800, 1200, originals, mode)
    [landscape] = size_pages(1200, 800, originals, mode)

    assert portrait == pytest.approx(portrait_size)
    assert landscape == pytest.approx(landscape_size)


@pytest.mark.parametrize(
    ("width", "height", "pages"),
    [
        (1200, 800, []),
        (0, 800, [{"width": 1000, "height": 1600}]),
        (1200, 0, [{"width": 1000, "height": 1600}]),
        (-1, 800, [{"width": 1000, "height": 1600}]),
        (1200, 800, [{"width": 0, "height": 1600}]),
        (1200, 800, [{"width": 1000, "height": 0}]),
        (1200, 800, [{"width": -1000, "height": 1600}]),
    ],
)
def test_unmeasured_or_invalid_pages_do_not_produce_invalid_css(size_pages, width, height, pages):
    assert size_pages(width, height, pages) == []
