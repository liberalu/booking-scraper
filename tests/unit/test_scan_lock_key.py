"""The advisory-lock key must be identical in every process.

`abs(hash(phase))` was not: CPython randomises string hashing per
interpreter, so two spiders computed different keys for the same phase and
both acquired the lock that is supposed to exclude them.
"""

import subprocess
import sys
import zlib

from book_scraper.db.repo import scan_lock_key

PHASES = ("scan", "discover", "validate", "match")


def test_key_is_crc32_masked_to_31_bits():
    for phase in PHASES:
        assert scan_lock_key(phase) == zlib.crc32(phase.encode()) & 0x7FFFFFFF
        assert 0 <= scan_lock_key(phase) <= 0x7FFFFFFF


def test_key_survives_a_different_hash_seed():
    # The bug reproduces only across processes, so this needs a subprocess
    # with hash randomisation actually on and seeded differently.
    script = (
        "from book_scraper.db.repo import scan_lock_key;"
        f"print(','.join(str(scan_lock_key(p)) for p in {PHASES!r}))"
    )
    seen = set()
    for seed in ("1", "424242"):
        out = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            check=True,
            env={"PYTHONHASHSEED": seed, "PYTHONPATH": "."},
        )
        seen.add(out.stdout.strip())

    assert len(seen) == 1
    assert seen.pop() == ",".join(str(scan_lock_key(p)) for p in PHASES)
