#!/usr/bin/env python3
"""Build docs/superpowers/specs/INDEX.md from the specs in this folder.

Reads each `*-design.md` (and any other top-level `*.md`) under
`docs/superpowers/specs/`, parses its title (`# …` on line 1), `**Status:** …`
header, and a one-line summary (`**Goal:** …` or the first non-empty line
under `## Overview` / `## Goal` / `## Problem` / `## Context`), and writes
INDEX.md grouped by status.

Run from anywhere:
    python3 docs/superpowers/scripts/build-spec-index.py

The script is intentionally dependency-free — pure stdlib.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SPECS_DIR = REPO_ROOT / "docs" / "superpowers" / "specs"
INDEX_FILE = SPECS_DIR / "INDEX.md"

STATUS_RE = re.compile(r"^\*\*Status:\*\*\s*(.+?)\s*$", re.MULTILINE)
GOAL_RE = re.compile(r"^\*\*Goal:\*\*\s*(.+?)\s*$", re.MULTILINE)
SECTION_HEAD_RE = re.compile(r"^##\s+(Overview|Goal|Problem|Context)\b", re.MULTILINE)


def extract(path: Path) -> tuple[str, str, str]:
    text = path.read_text(encoding="utf-8")
    # Title from the first `# …` heading.
    title_match = re.search(r"^#\s+(.+?)$", text, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else path.stem
    status_match = STATUS_RE.search(text)
    status = status_match.group(1).strip() if status_match else "(missing)"
    summary = ""
    goal_match = GOAL_RE.search(text)
    if goal_match:
        summary = goal_match.group(1).strip()
    else:
        sec_match = SECTION_HEAD_RE.search(text)
        if sec_match:
            tail = text[sec_match.end():]
            for line in tail.splitlines():
                line = line.strip()
                if line:
                    summary = line
                    break
    return title, status, summary


def bucket(status: str) -> str:
    s = status.lower()
    if "draft" in s and "not yet" in s:
        return "Draft — unbuilt"
    if "partial" in s:
        return "In progress / Partial"
    if "approved" in s or "ready for" in s:
        return "Approved — awaiting build"
    if "design" in s and "approved" not in s:
        return "Design — pre-approval"
    if "active" in s and "implemented" not in s:
        return "Active reference (not a feature)"
    if "implemented" in s or "shipped" in s:
        return "Implemented"
    if "(missing)" in s:
        return "Unknown — needs status"
    return "Other / Needs review"


ORDER = [
    "Draft — unbuilt",
    "Approved — awaiting build",
    "Design — pre-approval",
    "In progress / Partial",
    "Unknown — needs status",
    "Other / Needs review",
    "Implemented",
    "Active reference (not a feature)",
]


def main() -> int:
    if not SPECS_DIR.is_dir():
        print(f"specs dir not found: {SPECS_DIR}", file=sys.stderr)
        return 1
    entries: list[tuple[str, str, str, str]] = []
    for spec in sorted(SPECS_DIR.glob("*.md")):
        if spec.name == "INDEX.md":
            continue
        title, status, summary = extract(spec)
        entries.append((spec.name, title, status, summary))

    buckets: dict[str, list[tuple[str, str, str, str]]] = {}
    for e in entries:
        buckets.setdefault(bucket(e[2]), []).append(e)

    out: list[str] = []
    out.append("# Specs Index")
    out.append("")
    out.append("Single source of truth for every design spec under `docs/superpowers/specs/`,")
    out.append("grouped by `**Status:**` header. Use this to see what's queued, in progress, and shipped.")
    out.append("")
    out.append("**Adding a new feature idea?** Create a new `YYYY-MM-DD-name-design.md` here with a `**Status:** Draft` header. It'll show up in the `Draft — unbuilt` bucket on the next regenerate.")
    out.append("")
    out.append("**Shipped a spec?** Change its `**Status:**` line to `Implemented` (and optionally cite the commits).")
    out.append("")
    out.append("**Regenerate this index:**")
    out.append("")
    out.append("```bash")
    out.append("python3 docs/superpowers/scripts/build-spec-index.py")
    out.append("```")
    out.append("")
    out.append(f"**Total specs:** {len(entries)}")
    out.append("")
    for b in ORDER:
        specs = buckets.get(b, [])
        if not specs:
            continue
        out.append(f"## {b} ({len(specs)})")
        out.append("")
        for fname, title, status, summary in sorted(specs):
            # Take just the first sentence of the summary for compactness.
            short = summary.split(". ")[0].strip()
            if short and not short.endswith("."):
                short += "."
            out.append(f"- **[{title}]({fname})**")
            out.append(f"  - Status: _{status}_")
            if short:
                out.append(f"  - {short}")
            out.append("")

    INDEX_FILE.write_text("\n".join(out), encoding="utf-8")
    print(f"Wrote {INDEX_FILE} ({len(entries)} specs)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
