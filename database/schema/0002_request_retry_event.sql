ALTER TABLE public.scrape_run_events
    DROP CONSTRAINT ck_scrape_run_events_event_type;

ALTER TABLE public.scrape_run_events
    ADD CONSTRAINT ck_scrape_run_events_event_type
    CHECK (event_type::text = ANY (ARRAY[
        'started',
        'paused',
        'resumed',
        'stop_requested',
        'retry_failures',
        'request_retried',
        'rerun',
        'continued',
        'resumed_after_failure',
        'restarted',
        'completed',
        'failed',
        'subdivided',
        'chain_skipped'
    ]::text[]));
