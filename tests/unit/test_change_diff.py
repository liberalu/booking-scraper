from book_scraper.dashboard.app import _change_diff


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


def test_long_change_collapses_into_details():
    old = "alpha " * 60
    new = "beta " * 60
    html = str(_change_diff(old, new, limit=200))
    assert "<details" in html
    assert "<summary>" in html
    assert "change-diff-body" in html


def test_long_change_summary_is_truncated():
    old = "word " * 100
    new = "different " * 100
    html = str(_change_diff(old, new, limit=80))
    start = html.index("<summary>") + len("<summary>")
    end = html.index("</summary>")
    summary = html[start:end]
    assert summary.endswith("…")
    # Summary should be plaintext (no raw <del>/<ins>) and under the limit.
    assert "<del>" not in summary
    assert "<ins>" not in summary
    # +1 for the trailing ellipsis char.
    assert len(summary) <= 80 + 1


def test_html_in_values_is_escaped():
    html = str(
        _change_diff("<script>", "<b>safe</b>", limit=500)
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
