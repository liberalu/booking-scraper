import difflib
import re
import time
from datetime import UTC, datetime
from pathlib import Path

import markdown as _markdown
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from markupsafe import Markup, escape

from book_scraper.dashboard.deps import templates
from book_scraper.dashboard.routes import (
    api as api_routes,
)
from book_scraper.dashboard.routes import (
    cron,
    prices,
    runs,
    scrape,
    shop_books,
    shops,
    urls,
    validation,
)

# Detects a real HTML tag (`<p>`, `<strong>`, `</div>`, …) so we don't
# misclassify text with incidental < or > as HTML. Lithuanian source
# text often quotes with "<...>" as an ellipsis marker.
_HTML_TAG_RE = re.compile(r"<[a-zA-Z/][^>]*>")


def _relative_time(dt: "datetime | None") -> str:
    """Return human-friendly relative time string, e.g. '3d ago'."""
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    delta = datetime.now(UTC) - dt
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    if days < 7:
        return f"{days}d ago"
    weeks = days // 7
    if weeks < 5:
        return f"{weeks}w ago"
    months = days // 30
    if months < 12:
        return f"{months}mo ago"
    years = days // 365
    return f"{years}y ago"


def _render_description(text: str | None) -> Markup:
    """Render a shop_book description for display.

    - If the stored value contains real HTML tags, pass it through as-is
      (legacy rows scraped before the Markdown migration).
    - Otherwise render as Markdown.
    Empty / None returns an empty Markup so templates can call it
    unconditionally.
    """
    if not text:
        return Markup("")
    if _HTML_TAG_RE.search(text):
        return Markup(text)
    html = _markdown.markdown(text, extensions=["extra", "nl2br"])
    return Markup(html)


def _diff_chunks(old: str, new: str) -> list[tuple[str, str]]:
    """Word-level diff returning [(kind, text), …] where kind is one of
    'equal' | 'del' | 'ins'. Empty chunks are dropped.
    """
    old_tokens = old.split()
    new_tokens = new.split()
    matcher = difflib.SequenceMatcher(a=old_tokens, b=new_tokens)
    chunks: list[tuple[str, str]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            if i1 < i2:
                chunks.append(("equal", " ".join(old_tokens[i1:i2])))
        elif tag == "delete":
            if i1 < i2:
                chunks.append(("del", " ".join(old_tokens[i1:i2])))
        elif tag == "insert":
            if j1 < j2:
                chunks.append(("ins", " ".join(new_tokens[j1:j2])))
        elif tag == "replace":
            if i1 < i2:
                chunks.append(("del", " ".join(old_tokens[i1:i2])))
            if j1 < j2:
                chunks.append(("ins", " ".join(new_tokens[j1:j2])))
    return chunks


def _render_chunks(chunks: list[tuple[str, str]]) -> str:
    """Render [(kind, text)] chunks as escaped HTML with <del>/<ins>."""
    parts: list[str] = []
    for kind, text in chunks:
        if not text:
            continue
        if kind == "equal":
            parts.append(escape(text))
        elif kind == "del":
            parts.append(f"<del>{escape(text)}</del>")
        elif kind == "ins":
            parts.append(f"<ins>{escape(text)}</ins>")
    return " ".join(parts)


def _summary_chunks(
    chunks: list[tuple[str, str]], limit: int, context_words: int = 4
) -> tuple[list[tuple[str, str]], bool, bool]:
    """Pick a window around the first change for the <summary>.

    Returns (window, truncated_start, truncated_end) — truncated flags
    tell the caller whether to prepend/append "…".
    """
    first = next((i for i, (k, _) in enumerate(chunks) if k != "equal"), None)
    if first is None:
        return [], False, False

    window: list[tuple[str, str]] = []
    truncated_start = False
    truncated_end = False

    # Prefix: last `context_words` words of the equal chunk before the
    # first change (if any).
    if first > 0:
        prev_kind, prev_text = chunks[first - 1]
        if prev_kind == "equal":
            words = prev_text.split()
            if len(words) > context_words:
                window.append(("equal", " ".join(words[-context_words:])))
                truncated_start = True
            else:
                window.append((prev_kind, prev_text))
        if first > 1:
            truncated_start = True

    # Walk forward from `first`, greedily accumulating until we'd blow
    # the char budget. Include at least the first change in full.
    current_len = sum(len(t) + 1 for _, t in window)
    i = first
    change_included = False
    while i < len(chunks):
        kind, text = chunks[i]
        if kind == "equal":
            words = text.split()
            # After we've included at least one change, allow up to
            # `context_words` trailing equal words, then stop.
            if change_included:
                if len(words) > context_words:
                    window.append(("equal", " ".join(words[:context_words])))
                    truncated_end = i + 1 < len(chunks) or len(words) > context_words
                else:
                    window.append((kind, text))
                    truncated_end = i + 1 < len(chunks)
                break
            window.append((kind, text))
            current_len += len(text) + 1
            i += 1
            continue
        # Deletion / insertion chunk.
        window.append((kind, text))
        current_len += len(text) + 1
        change_included = True
        if current_len >= limit:
            truncated_end = i + 1 < len(chunks)
            break
        i += 1
    else:
        # Ran off the end without hitting the break.
        truncated_end = False

    return window, truncated_start, truncated_end


def _change_diff(old: str | None, new: str | None, limit: int = 200) -> Markup:
    """Render a shop_book-change as a word-level inline diff.

    - Short changes (combined chars ≤ `limit`) render inline with
      <del>/<ins> markup.
    - Longer changes render a <details> whose <summary> is a windowed
      snippet around the first change (so you can see the actual
      red/green delta before expanding), and whose body is the full
      inline diff.
    """
    old_s = "" if old is None else str(old)
    new_s = "" if new is None else str(new)
    if not old_s and not new_s:
        return Markup('<span class="text-muted">—</span>')

    chunks = _diff_chunks(old_s, new_s)
    full_html = _render_chunks(chunks)

    if len(old_s) + len(new_s) <= limit:
        return Markup(full_html)

    window, trunc_start, trunc_end = _summary_chunks(chunks, limit)
    if not window:
        return Markup('<span class="text-muted">(no change)</span>')
    summary_html = _render_chunks(window)
    if trunc_start:
        summary_html = "… " + summary_html
    if trunc_end:
        summary_html = summary_html + " …"
    return Markup(
        f'<details class="change-diff">'
        f"<summary>{summary_html}</summary>"
        f'<div class="change-diff-body">{full_html}</div>'
        f"</details>"
    )


templates.env.filters["markdown"] = _render_description
templates.env.filters["relative_time"] = _relative_time
templates.env.globals["change_diff"] = _change_diff

app = FastAPI(title="Book Scraper Dashboard")

app.mount(
    "/static",
    StaticFiles(directory=str(Path(__file__).parent / "static")),
    name="static",
)

app.include_router(api_routes.router, prefix="/api")


_SPA_BUILD_VERSION = str(int(time.time()))
_SPA_INDEX_PATH = Path(__file__).parent / "static" / "hifi" / "index.html"


@app.get("/")
async def spa_index() -> HTMLResponse:
    """Serve the SPA entry with versioned JSX URLs for cache busting."""
    html = _SPA_INDEX_PATH.read_text(encoding="utf-8")
    html = html.replace('.jsx"', f'.jsx?v={_SPA_BUILD_VERSION}"')
    return HTMLResponse(
        html,
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )


app.include_router(shops.router)
app.include_router(shop_books.router)
app.include_router(runs.router)
app.include_router(urls.router)
app.include_router(validation.router)
app.include_router(prices.router)
app.include_router(scrape.router)
app.include_router(cron.router)
