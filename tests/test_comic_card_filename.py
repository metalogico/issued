from pathlib import Path

import jinja2

from reader.routes._common import templates as app_templates


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = PROJECT_ROOT / "reader" / "templates"
EXTENSION = "comic-filename-extension"


def template_env() -> jinja2.Environment:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(TEMPLATES),
        autoescape=app_templates.env.autoescape,
    )
    env.globals["url_path"] = lambda *args, **kwargs: "/reader/comic"
    return env


def render_comic_filename(filename: str) -> str:
    template = template_env().from_string(
        "{% from 'macros/comic-filename.html' import comic_filename %}"
        "{{ comic_filename(filename) }}"
    )
    return template.render(filename=filename)


def test_comic_filename_markup():
    issue = render_comic_filename("Issue 1.cbz")
    assert f'Issue 1<span class="{EXTENSION}">.cbz</span>' in issue
    assert "Issue 1 <span" not in issue

    archive = render_comic_filename("Archive.tar.cbz")
    assert f'Archive.tar<span class="{EXTENSION}">.cbz</span>' in archive

    readme = render_comic_filename("README")
    assert EXTENSION not in readme
    assert '<span class="line-clamp-2 block text-center text-sm font-medium text-gray-800">README</span>' in readme

    dotfile = render_comic_filename(".cbz")
    assert EXTENSION not in dotfile
    assert '<span class="line-clamp-2 block text-center text-sm font-medium text-gray-800">.cbz</span>' in dotfile


def test_continue_reading_title_hides_with_the_same_extension_span():
    html = template_env().get_template("partials/continue-reading.html").render(
        continue_reading_comics=[
            {
                "uuid": "abc",
                "filename": "Issue 1.cbz",
                "page_count": 12,
                "current_page": 3,
            }
        ],
        request=None,
    )

    assert "text-xs" in html
    assert f'Issue 1<span class="{EXTENSION}">.cbz</span>' in html
    assert "12 pages" in html


def test_last_added_and_table_titles_use_the_extension_span():
    env = template_env()
    comic = {"uuid": "abc", "filename": "Archive.tar.cbz", "page_count": 20}

    last_added = env.get_template("partials/last-added.html").render(
        show_last_added=True,
        last_added_comics=[comic],
        request=None,
    )
    assert "text-xs" in last_added
    assert f'Archive.tar<span class="{EXTENSION}">.cbz</span>' in last_added
    assert "20 pages" in last_added

    table = env.from_string(
        "{% from 'partials/comics-section.html' import comic_table %}"
        "{{ comic_table(comics, request) }}"
    ).render(comics=[comic], request=None)
    assert (
        '<p class="font-semibold text-gray-900 leading-snug line-clamp-2">'
        f'Archive.tar<span class="{EXTENSION}">.cbz</span></p>'
    ) in table
