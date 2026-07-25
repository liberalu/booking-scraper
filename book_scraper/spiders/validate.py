"""Validate phase spider.

Thin wrapper around ValidateService — the run lifecycle (create run,
heartbeat ordering, off-reactor dispatch, finish, close failsafe) lives in
ServiceSpider. All this adds is the service call and the per-run counter
log line.
"""

from __future__ import annotations

from typing import Any

from book_scraper.services.validate import ValidateService
from book_scraper.spiders.service_spider import ServiceSpider


class ValidateSpider(ServiceSpider):
    name = "validate"
    phase = "validate"

    def run_service(self, session: Any, shop_id: int, run_id: int) -> Any:
        return ValidateService(session).run(shop_id, run_id)

    def finalize_result(self, session: Any, run_id: int, result: Any) -> None:
        """Log the per-issue emit counts for this run.

        The only visibility into "did this check actually fire on real
        data?" at runtime. `resolve_gone_issues` unconditionally marks every
        open issue not re-emitted by the current run as resolved (db/repo.py
        `resolve_gone_issues`), so a zero-count check silently wipes the
        backlog for that type.

        Emitted as a single `key=value` line so Loki / LogQL can `| logfmt`
        and graph per-issue counts over time — dashboard alarms can then fire
        on "any issue_type that historically emits > N suddenly drops to 0".
        Counter values are ints and issue keys are snake_case, both
        logfmt-safe without quoting.
        """
        counters: dict[str, int] = result or {}
        total = sum(counters.values())
        detail = " ".join(f"{k}={v}" for k, v in sorted(counters.items()))
        self.logger.info(
            "validate_counters run_id=%d shop=%s total=%d distinct=%d %s",
            run_id,
            self.shop_name,
            total,
            len(counters),
            detail,
        )
