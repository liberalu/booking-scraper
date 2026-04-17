import difflib
import re
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

# Detects a real HTML tag (`<p>`, `<strong>`, `</div>`, …) so we don't
# misclassify text with incidental < or > as HTML. Lithuanian source
# text often quotes with "<...>" as an ellipsis marker.
_HTML_TAG_RE = re.compile(r"<[a-zA-Z/][^>]*>")


def _render_description(text: str | None) -> Markup:
    """Render a listing description for display.

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


def _git_style_diff(old: str, new: str, context: int = 1) -> str:
    """Unified-diff HTML for `old` vs `new`.

    Each chunk is a sequence of `<div class="diff-line ...">` lines:
      - `diff-line-del` for removed lines (prefixed `-`)
      - `diff-line-add` for added lines (prefixed `+`)
      - `diff-line-ctx` for unchanged context (prefixed two spaces)
    Hunks are separated by a `<div class="diff-hunk-sep">…</div>` row
    so long unchanged passages don't drown the view.

    `context` is the number of unchanged lines to keep around each
    change (like `git diff -Un`).
    """
    old_lines = old.splitlines() or [""]
    new_lines = new.splitlines() or [""]
    matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
    out: list[str] = []
    opcodes = matcher.get_opcodes()
    last_change_end_i = 0
    previous_was_sep = False
    for op_idx, (tag, i1, i2, j1, j2) in enumerate(opcodes):
        if tag == "equal":
            span = i2 - i1
            is_first = op_idx == 0
            is_last = op_idx == len(opcodes) - 1
            if is_first and is_last:
                # No changes at all; nothing useful to render.
                continue
            if is_first:
                # Keep only the trailing `context` lines before the
                # first change.
                start = max(i1, i2 - context)
                for k in range(start, i2):
                    out.append(
                        f'<div class="diff-line diff-line-ctx">'
                        f"  {escape(old_lines[k])}</div>"
                    )
                previous_was_sep = start > i1
            elif is_last:
                end = min(i2, i1 + context)
                for k in range(i1, end):
                    out.append(
                        f'<div class="diff-line diff-line-ctx">'
                        f"  {escape(old_lines[k])}</div>"
                    )
                previous_was_sep = end < i2
            elif span <= context * 2:
                # Small unchanged gap — keep the whole thing as context.
                for k in range(i1, i2):
                    out.append(
                        f'<div class="diff-line diff-line-ctx">'
                        f"  {escape(old_lines[k])}</div>"
                    )
                previous_was_sep = False
            else:
                # Trailing context of previous hunk
                for k in range(i1, i1 + context):
                    out.append(
                        f'<div class="diff-line diff-line-ctx">'
                        f"  {escape(old_lines[k])}</div>"
                    )
                # Separator between hunks
                if not previous_was_sep:
                    out.append(
                        '<div class="diff-hunk-sep">…</div>'
                    )
                    previous_was_sep = True
                # Leading context of next hunk
                for k in range(i2 - context, i2):
                    out.append(
                        f'<div class="diff-line diff-line-ctx">'
                        f"  {escape(old_lines[k])}</div>"
                    )
            last_change_end_i = i2
            continue
        for k in range(i1, i2):
            out.append(
                f'<div class="diff-line diff-line-del">'
                f"- {escape(old_lines[k])}</div>"
            )
        for k in range(j1, j2):
            out.append(
                f'<div class="diff-line diff-line-add">'
                f"+ {escape(new_lines[k])}</div>"
            )
        previous_was_sep = False
        last_change_end_i = i2
    _ = last_change_end_i  # silence unused
    return "".join(out)


def _change_summary(old: str, new: str, limit: int) -> str:
    """Short plain-text summary used as the <details><summary>.

    Shows the first meaningful delta line (`- ...` then `+ ...`) so the
    reader can tell what changed before expanding.
    """
    matcher = difflib.SequenceMatcher(
        a=old.splitlines() or [""],
        b=new.splitlines() or [""],
        autojunk=False,
    )
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        parts: list[str] = []
        if i1 < i2:
            first_del = (old.splitlines() or [""])[i1]
            parts.append(f"- {first_del}")
        if j1 < j2:
            first_add = (new.splitlines() or [""])[j1]
            parts.append(f"+ {first_add}")
        text = " · ".join(parts)
        if len(text) > limit:
            text = text[:limit].rstrip() + "…"
        return text
    return "(no change)"


def _change_diff(
    old: str | None, new: str | None, limit: int = 200
) -> Markup:
    """Render a listing-change as a git-style line-level diff.

    Short single-line changes (≤ `limit` combined chars, no newlines on
    either side) render inline with <del>/<ins> for quick scanning.
    Longer or multi-line changes render a <details> block whose
    <summary> shows the first diff line (truncated to `limit`) and
    whose body is the full git-style diff.
    """
    old_s = "" if old is None else str(old)
    new_s = "" if new is None else str(new)
    if not old_s and not new_s:
        return Markup('<span class="text-muted">—</span>')

    short_and_singleline = (
        "\n" not in old_s
        and "\n" not in new_s
        and len(old_s) + len(new_s) <= limit
    )
    if short_and_singleline:
        old_tokens = old_s.split()
        new_tokens = new_s.split()
        matcher = difflib.SequenceMatcher(a=old_tokens, b=new_tokens)
        parts: list[str] = []
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                parts.append(escape(" ".join(old_tokens[i1:i2])))
            elif tag == "delete":
                parts.append(
                    f"<del>{escape(' '.join(old_tokens[i1:i2]))}</del>"
                )
            elif tag == "insert":
                parts.append(
                    f"<ins>{escape(' '.join(new_tokens[j1:j2]))}</ins>"
                )
            elif tag == "replace":
                parts.append(
                    f"<del>{escape(' '.join(old_tokens[i1:i2]))}</del>"
                )
                parts.append(
                    f"<ins>{escape(' '.join(new_tokens[j1:j2]))}</ins>"
                )
        return Markup(" ".join(p for p in parts if p))

    diff_body = _git_style_diff(old_s, new_s)
    summary = _change_summary(old_s, new_s, limit)
    return Markup(
        f'<details class="change-diff">'
        f"<summary>{escape(summary)}</summary>"
        f'<pre class="change-diff-body">{diff_body}</pre>'
        f"</details>"
    )


templates.env.filters["markdown"] = _render_description
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
