#!/usr/bin/env python
"""Dump what the pipeline stores for real product descriptions.

    PYTHONPATH=. uv run python php/tools/dump_markdown_golden.py

The Python validation pipeline converts every scraped description from HTML to
Markdown before storing it, and production holds zero HTML descriptions — so a
port that stores the raw HTML regresses every book. That exact output is
therefore part of the contract, and this captures it over the bundled fixtures
plus a set of live pages, so the PHP converter can be held to it.

It calls `pipelines.html_to_markdown` rather than markdownify directly: the
pipeline normalises `<br/>` first and maps an empty conversion to None, and a
second copy of that logic here would let the golden drift from what is stored.

Written to php/tests/golden/descriptions.json and asserted by MarkdownTest.
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

from book_scraper.pipelines import html_to_markdown as convert
from book_scraper.spiders.registry import load_parsers

OUT = Path(__file__).resolve().parents[1] / "tests" / "golden" / "descriptions.json"

# Live pages, chosen for markup variety rather than content.
LIVE = [
    ("vaga", "https://vaga.lt/ketvertas"),
    ("vaga", "https://vaga.lt/stebuklingi-metai"),
    ("vaga", "https://vaga.lt/durniu-mokykla"),
    ("vaga", "https://vaga.lt/laimingos-smegenys"),
    ("vaga", "https://vaga.lt/gera-tokia-kokia-yra"),
    ("vaga", "https://vaga.lt/sirdies-kauleliai"),
]

# Hand-written shapes for the tags real pages don't happen to carry. These
# still go through markdownify, so they are golden output, not guesses.
SYNTHETIC = [
    ("heading", "<h1>Title</h1><h2>Sub</h2><p>Body</p>"),
    ("list_unordered", "<ul><li>One</li><li>Two</li></ul>"),
    ("list_ordered", "<ol><li>First</li><li>Second</li></ol>"),
    ("link", '<p>See <a href="https://example.com">the site</a>.</p>'),
    ("blockquote", "<blockquote><p>Quoted</p></blockquote>"),
    ("nested_emphasis", "<p><i><b>both</b></i> and <b>bold</b> and <em>em</em></p>"),
    ("line_breaks", "<p>One<br>Two<br/>Three</p>"),
    ("entities", "<p>a &amp; b &lt; c &gt; d &nbsp; e &quot;q&quot;</p>"),
    ("double_space", "<p>two  spaces and\ttab</p>"),
    ("brackets", "<p>a [bracketed] thing and an * asterisk and _under_</p>"),
    ("empty", "<p></p>"),
    ("div_span", '<div>outer <span>inner</span></div>'),
    ("table", "<table><tr><th>H</th></tr><tr><td>C</td></tr></table>"),
    ("pre_code", "<pre><code>x = 1</code></pre>"),
    ("hr", "<p>a</p><hr><p>b</p>"),
    ("image", '<p><img src="x.png" alt="Alt"></p>'),
    ("deep_nesting", "<p><b>a <i>b <u>c</u></i></b></p>"),
    ("whitespace_only", "<p>   </p>"),
    # The U+00A0 cases. A trailing one is dropped at a block edge, but a
    # `<br>` after it shields it — shops emit `…&nbsp;<br></p>` constantly,
    # so this decides the stored text of a large share of descriptions.
    ("nbsp_trailing", "<p>a.\u00a0</p><p>b</p>"),
    ("nbsp_before_break", "<p>a.\u00a0<br></p><p>b</p>"),
    ("break_trailing", "<p>a.<br></p><p>b</p>"),
    ("nbsp_both_sides_of_break", "<p>a.\u00a0<br>\u00a0</p><p>b</p>"),
    ("nbsp_mid_and_trailing", "<p>x\u00a0y.\u00a0</p><p>b</p>"),
    ("nbsp_inside_strong", "<p>Interviu su\u00a0</strong> <strong>Kauno</strong></p>"),
]


def fetch(url: str) -> str | None:
    request = urllib.request.Request(url, headers={"User-Agent": "Scrapy"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as error:
        print(f"  skip {url}: {error}", file=sys.stderr)
        return None


def main() -> None:
    cases = []

    for shop in ("vaga", "pegasas", "patogupirkti", "humanitas", "almalittera"):
        module = load_parsers(shop)
        paths = [
            path
            for pattern in (f"fixtures/{shop}/*", f"fixtures/{shop}*")
            for path in glob.glob(pattern)
            if os.path.isfile(path)
        ]
        for path in sorted(set(paths)):
            try:
                parsed = module.parse_product_page(
                    Path(path).read_text(encoding="utf-8", errors="replace")
                )
            except Exception:
                continue
            description = (parsed or {}).get("description")
            if isinstance(description, str) and re.search(r"<[a-zA-Z/]", description):
                cases.append({
                    "label": f"fixture:{os.path.basename(path)}",
                    "html": description,
                    "markdown": convert(description),
                })

    for shop, url in LIVE:
        body = fetch(url)
        if body is None:
            continue
        try:
            parsed = load_parsers(shop).parse_product_page(body)
        except Exception as error:
            print(f"  skip {url}: {error}", file=sys.stderr)
            continue
        description = (parsed or {}).get("description")
        if isinstance(description, str) and re.search(r"<[a-zA-Z/]", description):
            cases.append({
                "label": f"live:{url.rsplit('/', 1)[-1]}",
                "html": description,
                "markdown": convert(description),
            })

    for label, html in SYNTHETIC:
        cases.append({
            "label": f"synthetic:{label}",
            "html": html,
            "markdown": convert(html),
        })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(cases, indent=1, ensure_ascii=False) + "\n")
    tags: dict[str, int] = {}
    for case in cases:
        for tag in re.findall(r"</?([a-zA-Z][a-zA-Z0-9]*)", case["html"]):
            tags[tag.lower()] = tags.get(tag.lower(), 0) + 1
    print(f"wrote {len(cases)} cases to {OUT}")
    print("tags covered:", ", ".join(sorted(tags)))


if __name__ == "__main__":
    main()
