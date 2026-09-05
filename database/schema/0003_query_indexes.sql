CREATE INDEX IF NOT EXISTS ix_scrape_url_items_discovered_url_id
    ON public.scrape_url_items (discovered_url_id);

CREATE INDEX IF NOT EXISTS ix_shop_book_changes_run_changed
    ON public.shop_book_changes (scrape_run_id, changed_at DESC);

CREATE INDEX IF NOT EXISTS ix_prices_shop_book_scraped
    ON public.prices (shop_book_id, scraped_at DESC);

CREATE INDEX IF NOT EXISTS ix_shop_books_last_run_id
    ON public.shop_books (last_run_id);

CREATE INDEX IF NOT EXISTS ix_books_source_run_id
    ON public.books (source_run_id);

CREATE INDEX IF NOT EXISTS ix_validation_issues_first_seen_run_id
    ON public.validation_issues (first_seen_run_id);

CREATE INDEX IF NOT EXISTS ix_scrape_failures_discovered_url_id
    ON public.scrape_failures (discovered_url_id);

CREATE INDEX IF NOT EXISTS ix_scrape_failures_item_occurred
    ON public.scrape_failures (scrape_url_item_id, occurred_at DESC);

CREATE INDEX IF NOT EXISTS ix_scrape_runs_shop_phase_status
    ON public.scrape_runs (shop_id, phase, status);

CREATE INDEX IF NOT EXISTS ix_cron_jobs_chain_to_job_id
    ON public.cron_jobs (chain_to_job_id);

CREATE INDEX IF NOT EXISTS ix_categories_parent_id
    ON public.categories (parent_id);

CREATE INDEX IF NOT EXISTS ix_scrape_runs_shop_active
    ON public.scrape_runs (shop_id, id)
    WHERE status IN ('running', 'paused', 'stopping');
