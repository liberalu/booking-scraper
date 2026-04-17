from book_scraper.dashboard.app import (
    _change_diff,
    _git_style_diff,
    _render_description,
)


def test_short_singleline_renders_inline_with_del_ins():
    html = str(_change_diff("Alice Smith", "Bob Smith", limit=200))
    assert "<del>Alice</del>" in html
    assert "<ins>Bob</ins>" in html
    assert "Smith" in html
    assert "<details" not in html


def test_none_old_shows_only_insertion():
    html = str(_change_diff(None, "Hello", limit=200))
    assert "<ins>Hello</ins>" in html
    assert "<del>" not in html


def test_none_new_shows_only_deletion():
    html = str(_change_diff("Hello", None, limit=200))
    assert "<del>Hello</del>" in html
    assert "<ins>" not in html


def test_both_none_yields_dash():
    html = str(_change_diff(None, None, limit=200))
    assert "—" in html


def test_multiline_uses_git_style_details():
    old = "line 1\nline 2\nline 3"
    new = "line 1\nchanged\nline 3"
    html = str(_change_diff(old, new, limit=500))
    assert "<details" in html
    assert "change-diff-body" in html
    assert "diff-line-del" in html
    assert "diff-line-add" in html
    # Deleted line has "- " prefix, added has "+ "
    assert "- line 2" in html
    assert "+ changed" in html


def test_long_singleline_uses_details_with_summary_truncated():
    old = "word " * 80
    new = "different " * 80
    html = str(_change_diff(old, new, limit=80))
    assert "<details" in html
    start = html.index("<summary>") + len("<summary>")
    end = html.index("</summary>")
    summary = html[start:end]
    # Summary is escaped plain text starting with "-" or "+"
    assert summary.endswith("…")


def test_git_style_diff_shows_context_around_change():
    old = "a\nb\nc\nd\ne"
    new = "a\nb\nX\nd\ne"
    body = _git_style_diff(old, new)
    # The unchanged "b" and "d" lines become context (1 line each side).
    assert "diff-line-ctx" in body
    assert "- c" in body
    assert "+ X" in body


def test_git_style_diff_escapes_html_in_values():
    body = _git_style_diff("<script>", "<b>safe</b>")
    assert "<script>" not in body
    assert "&lt;script&gt;" in body


def test_render_description_markdown_text_becomes_html():
    html = str(_render_description("**Bold** text"))
    assert "<strong>Bold</strong>" in html


def test_render_description_existing_html_passes_through():
    html = str(_render_description("<p>Already HTML</p>"))
    assert html == "<p>Already HTML</p>"


def test_render_description_angle_brackets_are_not_html():
    # Lithuanian "<...>" elision shouldn't disable markdown rendering.
    html = str(_render_description("**Hello** <...> world"))
    assert "<strong>Hello</strong>" in html


def test_render_description_none_returns_empty():
    assert str(_render_description(None)) == ""
    assert str(_render_description("")) == ""
