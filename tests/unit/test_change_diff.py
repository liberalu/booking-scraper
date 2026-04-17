from book_scraper.dashboard.app import (
    _change_diff,
    _diff_chunks,
    _render_chunks,
    _render_description,
    _summary_chunks,
)


def test_short_change_renders_inline_with_del_ins():
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


def test_long_change_collapses_with_styled_summary():
    old = "alpha " * 60 + "pivot " + "beta " * 60
    new = "alpha " * 60 + "rewrite " + "beta " * 60
    html = str(_change_diff(old, new, limit=120))
    # Wrapped in details
    assert "<details" in html
    # Summary still contains the red/green markers so the diff is
    # visible without clicking.
    start = html.index("<summary>") + len("<summary>")
    end = html.index("</summary>")
    summary = html[start:end]
    assert "<del>pivot</del>" in summary
    assert "<ins>rewrite</ins>" in summary
    # Body has the full diff.
    body_start = html.index("change-diff-body")
    assert "<del>pivot</del>" in html[body_start:]
    assert "<ins>rewrite</ins>" in html[body_start:]


def test_long_change_summary_has_ellipsis_markers():
    old = "alpha " * 20 + "pivot " + "beta " * 20
    new = "alpha " * 20 + "rewrite " + "beta " * 20
    html = str(_change_diff(old, new, limit=80))
    start = html.index("<summary>") + len("<summary>")
    end = html.index("</summary>")
    summary = html[start:end]
    # The window was truncated on both sides, so we expect "…" markers.
    assert "…" in summary


def test_html_in_values_is_escaped():
    html = str(_change_diff("<script>", "<b>safe</b>", limit=500))
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_diff_chunks_categorises_correctly():
    chunks = _diff_chunks("a b c", "a X c")
    kinds = [k for k, _ in chunks]
    assert kinds == ["equal", "del", "ins", "equal"]


def test_render_chunks_produces_escaped_del_ins():
    html = _render_chunks([("equal", "a"), ("del", "<x>"), ("ins", "<y>")])
    assert "a" in html
    assert "<del>&lt;x&gt;</del>" in html
    assert "<ins>&lt;y&gt;</ins>" in html


def test_summary_chunks_includes_first_change_plus_context():
    chunks = [
        ("equal", "one two three four five"),
        ("del", "OLD"),
        ("ins", "NEW"),
        ("equal", "six seven eight nine ten"),
    ]
    window, trunc_start, trunc_end = _summary_chunks(chunks, limit=200, context_words=2)
    # Should include trailing 2 words of the prefix, the del+ins, and
    # leading 2 words of the suffix.
    kinds = [k for k, _ in window]
    assert "del" in kinds
    assert "ins" in kinds
    assert trunc_start is True  # skipped "one two three"
    assert trunc_end is True  # skipped "eight nine ten"


def test_render_description_markdown_text_becomes_html():
    html = str(_render_description("**Bold** text"))
    assert "<strong>Bold</strong>" in html


def test_render_description_existing_html_passes_through():
    html = str(_render_description("<p>Already HTML</p>"))
    assert html == "<p>Already HTML</p>"


def test_render_description_angle_brackets_are_not_html():
    html = str(_render_description("**Hello** <...> world"))
    assert "<strong>Hello</strong>" in html


def test_render_description_none_returns_empty():
    assert str(_render_description(None)) == ""
    assert str(_render_description("")) == ""
