CREATE EXTENSION IF NOT EXISTS pg_stat_statements WITH SCHEMA public;

ALTER TABLE public.scrape_url_items SET (
    autovacuum_vacuum_scale_factor = 0.02,
    autovacuum_analyze_scale_factor = 0.01
);
