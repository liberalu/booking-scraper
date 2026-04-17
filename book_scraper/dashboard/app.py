import difflib
from pathlib import Path

import markdown as _markdown
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from markupsafe import Markup, escape

from book_scraper.dashboard.deps import templates
from book_scraper.dashboard.routes import (
    listings,
    overview,
    prices,
    runs,
    scrape,
    shops,
    urls,
    validation,
)


def _render_markdown(text: str | None) -> Markup:
    """Render a Markdown string to safe HTML for Jinja.

    Returns an empty Markup for None / empty inputs so templates can
    apply the filter unconditionally. Uses CommonMark-ish features
    (fenced_code, tables, nl2br) because scraped descriptions rely on
    paragraphs and line breaks more than fancy formatting.
    """
    if not text:
        return Markup("")
    html = _markdown.markdown(text, extensions=["extra", "nl2br"])
    return Markup(html)


def _inline_diff_html(old: str, new: str) -> str:
    """Word-level diff between old/new as inline HTML.

    Deletions wrap in <del>, insertions wrap in <ins>. Safe-escaped.
    """
    old_tokens = old.split()
    new_tokens = new.split()
    matcher = difflib.SequenceMatcher(a=old_tokens, b=new_tokens)
    parts: list[str] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            parts.append(escape(" ".join(old_tokens[i1:i2])))
        elif tag == "delete":
            parts.append(f"<del>{escape(' '.join(old_tokens[i1:i2]))}</del>")
        elif tag == "insert":
            parts.append(f"<ins>{escape(' '.join(new_tokens[j1:j2]))}</ins>")
        elif tag == "replace":
            parts.append(f"<del>{escape(' '.join(old_tokens[i1:i2]))}</del>")
            parts.append(f"<ins>{escape(' '.join(new_tokens[j1:j2]))}</ins>")
    return " ".join(p for p in parts if p)


def _change_diff(
    old: str | None, new: str | None, limit: int = 200
) -> Markup:
    """Render a listing-change as a compact inline diff.

    Short changes (under `limit` combined chars) render inline.
    Long changes render a <details> block whose <summary> is a
    truncated word-diff preview and whose body is the full diff.
    """
    old_s = "" if old is None else str(old)
    new_s = "" if new is None else str(new)
    if not old_s and not new_s:
        return Markup("<span class=\"text-muted\">—</span>")
    diff_html = _inline_diff_html(old_s, new_s)
    combined_len = len(old_s) + len(new_s)
    if combined_len <= limit:
        return Markup(diff_html)
    # Long: build a truncated summary (plain text, no tags) plus a full
    # diff body the user can expand.
    preview_src = diff_html
    # Strip tags for the summary so we can safely truncate without
    # breaking markup. The <del>/<ins> won't show styling in summary
    # but that's the tradeoff for a safe truncation.
    plain = (
        preview_src.replace("<del>", "")
        .replace("</del>", "")
        .replace("<ins>", "")
        .replace("</ins>", "")
    )
    summary = plain[:limit].rstrip() + "…"
    return Markup(
        f'<details class="change-diff">'
        f"<summary>{summary}</summary>"
        f'<div class="change-diff-body">{diff_html}</div>'
        f"</details>"
    )


templates.env.filters["markdown"] = _render_markdown
templates.env.globals["change_diff"] = _change_diff

app = FastAPI(title="Book Scraper Dashboard")

app.mount(
    "/static",
    StaticFiles(directory=str(Path(__file__).parent / "static")),
    name="static",
)

app.include_router(overview.router)
app.include_router(shops.router)
app.include_router(listings.router)
app.include_router(runs.router)
app.include_router(urls.router)
app.include_router(validation.router)
app.include_router(prices.router)
app.include_router(scrape.router)
