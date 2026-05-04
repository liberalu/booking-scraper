"""Unit tests for reconcile_runs._select_spawns dedup + cap logic."""

from __future__ import annotations

from book_scraper.scripts.reconcile_runs import _select_spawns


def test_returns_all_when_under_cap_and_unique() -> None:
    orphans = [
        (1, "vaga", "discover_sitemap"),
        (2, "pegasas", "discover_lupasearch"),
    ]
    to_spawn, deferred = _select_spawns(orphans, max_spawns=3)
    assert to_spawn == orphans
    assert deferred == []


def test_dedups_same_shop_phase_keeping_first() -> None:
    """Two orphans for the same shop+phase: only the first spawns;
    the second is deferred. Spawning both would race anyway because
    the dashboard pre-flight refuses concurrent runs for that key."""
    orphans = [
        (1, "vaga", "discover_sitemap"),
        (2, "vaga", "discover_sitemap"),  # dup
        (3, "pegasas", "discover_lupasearch"),
    ]
    to_spawn, deferred = _select_spawns(orphans, max_spawns=3)
    assert to_spawn == [
        (1, "vaga", "discover_sitemap"),
        (3, "pegasas", "discover_lupasearch"),
    ]
    assert deferred == [(2, "vaga", "discover_sitemap")]


def test_caps_at_max_spawns_and_defers_rest() -> None:
    """Five distinct orphans with cap=3: first three spawn, last two
    are deferred and remain resumable for the next cycle / operator."""
    orphans = [
        (1, "a", "discover_sitemap"),
        (2, "b", "discover_sitemap"),
        (3, "c", "discover_sitemap"),
        (4, "d", "discover_sitemap"),
        (5, "e", "discover_sitemap"),
    ]
    to_spawn, deferred = _select_spawns(orphans, max_spawns=3)
    assert len(to_spawn) == 3
    assert to_spawn == orphans[:3]
    assert deferred == orphans[3:]


def test_dedup_does_not_consume_cap_budget() -> None:
    """Dedup'd orphans should NOT count against the cap — otherwise a
    flood of dups for one shop would block legitimately distinct
    orphans from spawning."""
    orphans = [
        (1, "vaga", "discover_sitemap"),
        (2, "vaga", "discover_sitemap"),  # dup, deferred
        (3, "vaga", "discover_sitemap"),  # dup, deferred
        (4, "pegasas", "discover_lupasearch"),
        (5, "kakava", "discover_sitemap"),
    ]
    to_spawn, deferred = _select_spawns(orphans, max_spawns=3)
    # Should spawn 3 distinct (vaga first, pegasas, kakava), defer 2 dups
    assert len(to_spawn) == 3
    assert {(s, p) for _, s, p in to_spawn} == {
        ("vaga", "discover_sitemap"),
        ("pegasas", "discover_lupasearch"),
        ("kakava", "discover_sitemap"),
    }
    assert len(deferred) == 2


def test_empty_input_returns_empty_lists() -> None:
    to_spawn, deferred = _select_spawns([], max_spawns=3)
    assert to_spawn == []
    assert deferred == []
