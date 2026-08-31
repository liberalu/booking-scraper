


SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;


CREATE TYPE public.book_author_role AS ENUM (
    'author',
    'translator',
    'narrator',
    'illustrator',
    'editor',
    'compiler'
);



CREATE TYPE public.book_data_source AS ENUM (
    'ibiblioteka',
    'shop_inferred',
    'manual'
);



CREATE TYPE public.book_isbn_type AS ENUM (
    'isbn10',
    'isbn13',
    'ebook',
    'audio',
    'unknown'
);



CREATE TYPE public.discovery_source AS ENUM (
    'sitemap',
    'category',
    'full_crawl'
);



CREATE TYPE public.match_method AS ENUM (
    'isbn',
    'fuzzy',
    'manual'
);



CREATE TYPE public.match_status AS ENUM (
    'unmatched',
    'matched',
    'uncertain'
);



CREATE TYPE public.scrape_phase AS ENUM (
    'discover_sitemap',
    'discover_categories',
    'discover_full_crawl',
    'scan',
    'discover_graphql',
    'discover_lupasearch',
    'discover_ibiblioteka_api',
    'match',
    'validate'
);



CREATE TYPE public.scrape_status AS ENUM (
    'running',
    'completed',
    'failed',
    'stopping',
    'paused'
);



CREATE TYPE public.scrape_url_status AS ENUM (
    'pending',
    'processing',
    'done',
    'failed'
);



CREATE TYPE public.shop_book_type AS ENUM (
    'book',
    'audio',
    'ebook',
    'non_book'
);



CREATE TYPE public.url_type AS ENUM (
    'unknown',
    'product',
    'non_product',
    'unreachable',
    'product_partial'
);



CREATE TYPE public.validation_lifecycle AS ENUM (
    'new',
    'acknowledged',
    'snoozed',
    'resolved'
);


SET default_table_access_method = heap;


CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);



CREATE TABLE public.authors (
    id integer NOT NULL,
    name text NOT NULL,
    normalized_name text NOT NULL,
    libis_code text,
    viaf_id text,
    isni text,
    wikidata_id text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);



CREATE SEQUENCE public.authors_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



ALTER SEQUENCE public.authors_id_seq OWNED BY public.authors.id;



CREATE TABLE public.book_authors (
    book_id integer NOT NULL,
    author_id integer NOT NULL,
    role public.book_author_role DEFAULT 'author'::public.book_author_role NOT NULL,
    "position" integer DEFAULT 0 NOT NULL
);



CREATE TABLE public.book_isbns (
    id integer NOT NULL,
    book_id integer NOT NULL,
    isbn text NOT NULL,
    isbn_type public.book_isbn_type DEFAULT 'unknown'::public.book_isbn_type NOT NULL
);



CREATE SEQUENCE public.book_isbns_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



ALTER SEQUENCE public.book_isbns_id_seq OWNED BY public.book_isbns.id;



CREATE TABLE public.books (
    id integer NOT NULL,
    data_source public.book_data_source NOT NULL,
    libis_code text,
    title text NOT NULL,
    title_full text,
    year integer,
    publisher_id integer,
    series_id integer,
    release_place text,
    type text,
    format text,
    pages integer,
    duration text,
    dimensions text,
    language text,
    translated_from text[],
    description text,
    cover_url text,
    upcoming_release boolean DEFAULT false NOT NULL,
    udc_codes text[],
    subjects text[],
    audience text,
    libis_rating numeric(3,2),
    libis_review_count integer,
    source_run_id integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    source_url text,
    CONSTRAINT ck_books_libis_code_for_ibiblioteka CHECK (((data_source <> 'ibiblioteka'::public.book_data_source) OR (libis_code IS NOT NULL)))
);



CREATE SEQUENCE public.books_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



ALTER SEQUENCE public.books_id_seq OWNED BY public.books.id;



CREATE TABLE public.categories (
    id integer NOT NULL,
    name text NOT NULL,
    slug character varying NOT NULL,
    parent_id integer
);



CREATE SEQUENCE public.categories_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



ALTER SEQUENCE public.categories_id_seq OWNED BY public.categories.id;



CREATE TABLE public.cron_jobs (
    id integer NOT NULL,
    shop_id integer NOT NULL,
    phase text NOT NULL,
    strategy text,
    args text DEFAULT ''::text NOT NULL,
    cron_expression text NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    last_run_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    chain_to_job_id integer
);



CREATE SEQUENCE public.cron_jobs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



ALTER SEQUENCE public.cron_jobs_id_seq OWNED BY public.cron_jobs.id;



CREATE TABLE public.discovered_urls (
    id integer NOT NULL,
    shop_id integer NOT NULL,
    url text NOT NULL,
    source public.discovery_source NOT NULL,
    url_type public.url_type DEFAULT 'unknown'::public.url_type NOT NULL,
    fail_count integer NOT NULL,
    last_http_status integer,
    last_checked_at timestamp with time zone,
    normalized_url text NOT NULL,
    first_seen_at timestamp with time zone NOT NULL,
    last_seen_at timestamp with time zone NOT NULL,
    last_seen_run_id integer,
    shop_book_id integer
);



CREATE SEQUENCE public.discovered_urls_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



ALTER SEQUENCE public.discovered_urls_id_seq OWNED BY public.discovered_urls.id;



CREATE TABLE public.shop_book_attributes (
    id integer NOT NULL,
    shop_book_id integer NOT NULL,
    key character varying(64) NOT NULL,
    value text
);



CREATE SEQUENCE public.listing_attributes_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



ALTER SEQUENCE public.listing_attributes_id_seq OWNED BY public.shop_book_attributes.id;



CREATE TABLE public.shop_book_changes (
    id bigint NOT NULL,
    shop_book_id integer NOT NULL,
    scrape_run_id integer,
    field character varying NOT NULL,
    old_value text,
    new_value text,
    changed_at timestamp with time zone NOT NULL
);



CREATE SEQUENCE public.listing_changes_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



ALTER SEQUENCE public.listing_changes_id_seq OWNED BY public.shop_book_changes.id;



CREATE TABLE public.shop_book_field_updates (
    id integer NOT NULL,
    shop_book_id integer NOT NULL,
    field character varying(64) NOT NULL,
    updated_at timestamp with time zone NOT NULL
);



CREATE SEQUENCE public.listing_field_updates_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



ALTER SEQUENCE public.listing_field_updates_id_seq OWNED BY public.shop_book_field_updates.id;



CREATE TABLE public.shop_books (
    id integer NOT NULL,
    shop_id integer NOT NULL,
    url text NOT NULL,
    title text NOT NULL,
    author text,
    isbn character varying,
    image_url text,
    match_status public.match_status NOT NULL,
    match_method public.match_method,
    is_active boolean NOT NULL,
    first_seen_at timestamp with time zone NOT NULL,
    last_seen_at timestamp with time zone NOT NULL,
    publisher character varying,
    year integer,
    description text,
    categories character varying[],
    sku character varying,
    format character varying,
    price numeric(10,2),
    price_original numeric(10,2),
    in_stock boolean DEFAULT true NOT NULL,
    last_run_id integer,
    last_run_action character varying,
    inactive_since timestamp with time zone,
    type public.shop_book_type DEFAULT 'book'::public.shop_book_type NOT NULL,
    created_run_id integer,
    planned_availability_date date,
    rating numeric(3,2),
    review_count integer,
    book_id integer
);



CREATE SEQUENCE public.listings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



ALTER SEQUENCE public.listings_id_seq OWNED BY public.shop_books.id;



CREATE TABLE public.prices (
    id bigint NOT NULL,
    shop_book_id integer NOT NULL,
    price numeric(10,2) NOT NULL,
    price_original numeric(10,2),
    in_stock boolean NOT NULL,
    scraped_at timestamp with time zone NOT NULL,
    discount_pct numeric(5,2) GENERATED ALWAYS AS (
CASE
    WHEN ((price_original IS NOT NULL) AND (price_original > (0)::numeric)) THEN round((((1)::numeric - (price / price_original)) * (100)::numeric), 2)
    ELSE NULL::numeric
END) STORED,
    scrape_run_id integer
);



CREATE SEQUENCE public.prices_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



ALTER SEQUENCE public.prices_id_seq OWNED BY public.prices.id;



CREATE TABLE public.publishers (
    id integer NOT NULL,
    name text NOT NULL,
    country text,
    libis_codes text[],
    created_at timestamp with time zone DEFAULT now() NOT NULL
);



CREATE SEQUENCE public.publishers_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



ALTER SEQUENCE public.publishers_id_seq OWNED BY public.publishers.id;



CREATE TABLE public.scrape_run_events (
    id integer NOT NULL,
    run_id integer NOT NULL,
    event_type character varying(40) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    actor character varying(20),
    payload jsonb,
    CONSTRAINT ck_scrape_run_events_event_type CHECK (((event_type)::text = ANY ((ARRAY['started'::character varying, 'paused'::character varying, 'resumed'::character varying, 'stop_requested'::character varying, 'retry_failures'::character varying, 'rerun'::character varying, 'continued'::character varying, 'resumed_after_failure'::character varying, 'restarted'::character varying, 'completed'::character varying, 'failed'::character varying, 'subdivided'::character varying, 'chain_skipped'::character varying])::text[])))
);



CREATE SEQUENCE public.run_events_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



ALTER SEQUENCE public.run_events_id_seq OWNED BY public.scrape_run_events.id;



CREATE TABLE public.scrape_failures (
    id integer NOT NULL,
    scrape_url_item_id integer NOT NULL,
    run_id integer NOT NULL,
    shop_id integer NOT NULL,
    url text NOT NULL,
    discovered_url_id integer,
    occurred_at timestamp with time zone DEFAULT now() NOT NULL,
    error_reason text,
    http_status integer,
    response_bytes integer,
    error_detail text,
    lifecycle_state public.validation_lifecycle DEFAULT 'new'::public.validation_lifecycle NOT NULL,
    acknowledged_at timestamp with time zone,
    acknowledged_note text
);



CREATE SEQUENCE public.scrape_failures_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



ALTER SEQUENCE public.scrape_failures_id_seq OWNED BY public.scrape_failures.id;



CREATE TABLE public.scrape_runs (
    id integer NOT NULL,
    shop_id integer NOT NULL,
    phase public.scrape_phase NOT NULL,
    status public.scrape_status NOT NULL,
    started_at timestamp with time zone NOT NULL,
    finished_at timestamp with time zone,
    urls_total integer,
    urls_processed integer NOT NULL,
    items_added integer DEFAULT 0 NOT NULL,
    items_updated integer DEFAULT 0 NOT NULL,
    errors_4xx integer DEFAULT 0 NOT NULL,
    errors_5xx integer DEFAULT 0 NOT NULL,
    error_count integer DEFAULT 0 NOT NULL,
    last_heartbeat timestamp with time zone,
    pid integer,
    resumable_after_failure boolean DEFAULT false NOT NULL,
    close_reason text
);



CREATE SEQUENCE public.scrape_runs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



ALTER SEQUENCE public.scrape_runs_id_seq OWNED BY public.scrape_runs.id;



CREATE TABLE public.scrape_url_items (
    id integer NOT NULL,
    run_id integer NOT NULL,
    shop_id integer NOT NULL,
    discovered_url_id integer,
    url text NOT NULL,
    status public.scrape_url_status DEFAULT 'pending'::public.scrape_url_status NOT NULL,
    created_at timestamp with time zone NOT NULL,
    claimed_at timestamp with time zone,
    done_at timestamp with time zone,
    url_type text DEFAULT 'product'::text NOT NULL,
    http_status integer,
    request_delay_s double precision,
    delay_source text,
    retry_count integer DEFAULT 0 NOT NULL,
    response_bytes integer,
    attempts integer DEFAULT 0 NOT NULL
);



CREATE SEQUENCE public.scrape_url_items_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



ALTER SEQUENCE public.scrape_url_items_id_seq OWNED BY public.scrape_url_items.id;



CREATE TABLE public.series (
    id integer NOT NULL,
    title text NOT NULL,
    libis_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);



CREATE SEQUENCE public.series_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



ALTER SEQUENCE public.series_id_seq OWNED BY public.series.id;



CREATE TABLE public.shop_authors (
    id integer NOT NULL,
    name character varying(255) NOT NULL,
    normalized_name character varying(255) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    canonical_author_id integer
);



CREATE SEQUENCE public.shop_authors_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



ALTER SEQUENCE public.shop_authors_id_seq OWNED BY public.shop_authors.id;



CREATE TABLE public.shop_book_authors (
    shop_book_id integer NOT NULL,
    author_id integer NOT NULL,
    "position" integer DEFAULT 0 NOT NULL
);



CREATE TABLE public.shop_settings (
    id integer NOT NULL,
    shop_id integer NOT NULL,
    key character varying(64) NOT NULL,
    value text NOT NULL,
    type character varying(16) DEFAULT 'str'::character varying NOT NULL
);



CREATE SEQUENCE public.shop_settings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



ALTER SEQUENCE public.shop_settings_id_seq OWNED BY public.shop_settings.id;



CREATE TABLE public.shops (
    id integer NOT NULL,
    name character varying NOT NULL,
    base_url character varying NOT NULL
);



CREATE SEQUENCE public.shops_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



ALTER SEQUENCE public.shops_id_seq OWNED BY public.shops.id;



CREATE TABLE public.url_classifications (
    id integer NOT NULL,
    discovered_url_id integer NOT NULL,
    book_score integer NOT NULL,
    is_book_product boolean NOT NULL,
    reasons jsonb NOT NULL,
    classified_at timestamp with time zone NOT NULL
);



CREATE SEQUENCE public.url_classifications_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



ALTER SEQUENCE public.url_classifications_id_seq OWNED BY public.url_classifications.id;



CREATE TABLE public.validation_issues (
    id integer NOT NULL,
    last_seen_run_id integer NOT NULL,
    url text NOT NULL,
    field character varying NOT NULL,
    issue character varying NOT NULL,
    raw_value text,
    shop_book_id integer,
    discovered_url_id integer,
    lifecycle_state public.validation_lifecycle DEFAULT 'new'::public.validation_lifecycle NOT NULL,
    acknowledged_at timestamp with time zone,
    shop_id integer NOT NULL,
    first_seen_run_id integer,
    run_count integer DEFAULT 1 NOT NULL,
    resolved_at timestamp with time zone,
    snoozed_until timestamp with time zone,
    CONSTRAINT ck_validation_issues_single_entity CHECK ((NOT ((shop_book_id IS NOT NULL) AND (discovered_url_id IS NOT NULL))))
);



CREATE SEQUENCE public.validation_issues_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



ALTER SEQUENCE public.validation_issues_id_seq OWNED BY public.validation_issues.id;



ALTER TABLE ONLY public.authors ALTER COLUMN id SET DEFAULT nextval('public.authors_id_seq'::regclass);



ALTER TABLE ONLY public.book_isbns ALTER COLUMN id SET DEFAULT nextval('public.book_isbns_id_seq'::regclass);



ALTER TABLE ONLY public.books ALTER COLUMN id SET DEFAULT nextval('public.books_id_seq'::regclass);



ALTER TABLE ONLY public.categories ALTER COLUMN id SET DEFAULT nextval('public.categories_id_seq'::regclass);



ALTER TABLE ONLY public.cron_jobs ALTER COLUMN id SET DEFAULT nextval('public.cron_jobs_id_seq'::regclass);



ALTER TABLE ONLY public.discovered_urls ALTER COLUMN id SET DEFAULT nextval('public.discovered_urls_id_seq'::regclass);



ALTER TABLE ONLY public.prices ALTER COLUMN id SET DEFAULT nextval('public.prices_id_seq'::regclass);



ALTER TABLE ONLY public.publishers ALTER COLUMN id SET DEFAULT nextval('public.publishers_id_seq'::regclass);



ALTER TABLE ONLY public.scrape_failures ALTER COLUMN id SET DEFAULT nextval('public.scrape_failures_id_seq'::regclass);



ALTER TABLE ONLY public.scrape_run_events ALTER COLUMN id SET DEFAULT nextval('public.run_events_id_seq'::regclass);



ALTER TABLE ONLY public.scrape_runs ALTER COLUMN id SET DEFAULT nextval('public.scrape_runs_id_seq'::regclass);



ALTER TABLE ONLY public.scrape_url_items ALTER COLUMN id SET DEFAULT nextval('public.scrape_url_items_id_seq'::regclass);



ALTER TABLE ONLY public.series ALTER COLUMN id SET DEFAULT nextval('public.series_id_seq'::regclass);



ALTER TABLE ONLY public.shop_authors ALTER COLUMN id SET DEFAULT nextval('public.shop_authors_id_seq'::regclass);



ALTER TABLE ONLY public.shop_book_attributes ALTER COLUMN id SET DEFAULT nextval('public.listing_attributes_id_seq'::regclass);



ALTER TABLE ONLY public.shop_book_changes ALTER COLUMN id SET DEFAULT nextval('public.listing_changes_id_seq'::regclass);



ALTER TABLE ONLY public.shop_book_field_updates ALTER COLUMN id SET DEFAULT nextval('public.listing_field_updates_id_seq'::regclass);



ALTER TABLE ONLY public.shop_books ALTER COLUMN id SET DEFAULT nextval('public.listings_id_seq'::regclass);



ALTER TABLE ONLY public.shop_settings ALTER COLUMN id SET DEFAULT nextval('public.shop_settings_id_seq'::regclass);



ALTER TABLE ONLY public.shops ALTER COLUMN id SET DEFAULT nextval('public.shops_id_seq'::regclass);



ALTER TABLE ONLY public.url_classifications ALTER COLUMN id SET DEFAULT nextval('public.url_classifications_id_seq'::regclass);



ALTER TABLE ONLY public.validation_issues ALTER COLUMN id SET DEFAULT nextval('public.validation_issues_id_seq'::regclass);



ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);



ALTER TABLE ONLY public.authors
    ADD CONSTRAINT authors_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.book_authors
    ADD CONSTRAINT book_authors_pkey PRIMARY KEY (book_id, author_id, role);



ALTER TABLE ONLY public.book_isbns
    ADD CONSTRAINT book_isbns_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.books
    ADD CONSTRAINT books_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.categories
    ADD CONSTRAINT categories_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.categories
    ADD CONSTRAINT categories_slug_key UNIQUE (slug);



ALTER TABLE ONLY public.cron_jobs
    ADD CONSTRAINT cron_jobs_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.discovered_urls
    ADD CONSTRAINT discovered_urls_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.shop_book_attributes
    ADD CONSTRAINT listing_attributes_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.shop_book_authors
    ADD CONSTRAINT listing_authors_pkey PRIMARY KEY (shop_book_id, author_id);



ALTER TABLE ONLY public.shop_book_changes
    ADD CONSTRAINT listing_changes_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.shop_book_field_updates
    ADD CONSTRAINT listing_field_updates_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.shop_books
    ADD CONSTRAINT listings_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.prices
    ADD CONSTRAINT prices_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.publishers
    ADD CONSTRAINT publishers_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.scrape_run_events
    ADD CONSTRAINT run_events_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.scrape_failures
    ADD CONSTRAINT scrape_failures_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.scrape_runs
    ADD CONSTRAINT scrape_runs_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.scrape_url_items
    ADD CONSTRAINT scrape_url_items_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.series
    ADD CONSTRAINT series_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.shop_authors
    ADD CONSTRAINT shop_authors_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.shop_settings
    ADD CONSTRAINT shop_settings_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.shops
    ADD CONSTRAINT shops_name_key UNIQUE (name);



ALTER TABLE ONLY public.shops
    ADD CONSTRAINT shops_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.authors
    ADD CONSTRAINT uq_authors_isni UNIQUE (isni);



ALTER TABLE ONLY public.authors
    ADD CONSTRAINT uq_authors_libis_code UNIQUE (libis_code);



ALTER TABLE ONLY public.authors
    ADD CONSTRAINT uq_authors_normalized_name UNIQUE (normalized_name);



ALTER TABLE ONLY public.authors
    ADD CONSTRAINT uq_authors_viaf_id UNIQUE (viaf_id);



ALTER TABLE ONLY public.authors
    ADD CONSTRAINT uq_authors_wikidata_id UNIQUE (wikidata_id);



ALTER TABLE ONLY public.book_isbns
    ADD CONSTRAINT uq_book_isbns_isbn UNIQUE (isbn);



ALTER TABLE ONLY public.books
    ADD CONSTRAINT uq_books_libis_code UNIQUE (libis_code);



ALTER TABLE ONLY public.discovered_urls
    ADD CONSTRAINT uq_discovered_urls_shop_normalized UNIQUE (shop_id, normalized_url);



ALTER TABLE ONLY public.publishers
    ADD CONSTRAINT uq_publishers_name UNIQUE (name);



ALTER TABLE ONLY public.scrape_url_items
    ADD CONSTRAINT uq_scrape_url_items_run_url UNIQUE (run_id, url);



ALTER TABLE ONLY public.series
    ADD CONSTRAINT uq_series_libis_code UNIQUE (libis_code);



ALTER TABLE ONLY public.series
    ADD CONSTRAINT uq_series_title UNIQUE (title);



ALTER TABLE ONLY public.shop_book_attributes
    ADD CONSTRAINT uq_shop_book_attribute_shop_book_key UNIQUE (shop_book_id, key);



ALTER TABLE ONLY public.shop_book_field_updates
    ADD CONSTRAINT uq_shop_book_field_updates_shop_book_field UNIQUE (shop_book_id, field);



ALTER TABLE ONLY public.shop_books
    ADD CONSTRAINT uq_shop_book_shop_url UNIQUE (shop_id, url);



ALTER TABLE ONLY public.shop_settings
    ADD CONSTRAINT uq_shop_settings_shop_key UNIQUE (shop_id, key);



ALTER TABLE ONLY public.url_classifications
    ADD CONSTRAINT url_classifications_discovered_url_id_key UNIQUE (discovered_url_id);



ALTER TABLE ONLY public.url_classifications
    ADD CONSTRAINT url_classifications_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.validation_issues
    ADD CONSTRAINT validation_issues_pkey PRIMARY KEY (id);



CREATE INDEX ix_book_authors_author_id ON public.book_authors USING btree (author_id);



CREATE INDEX ix_book_isbns_book_id ON public.book_isbns USING btree (book_id);



CREATE INDEX ix_books_data_source ON public.books USING btree (data_source);



CREATE INDEX ix_books_publisher_id ON public.books USING btree (publisher_id);



CREATE INDEX ix_books_series_id ON public.books USING btree (series_id);



CREATE INDEX ix_books_year ON public.books USING btree (year);



CREATE INDEX ix_cron_jobs_shop_enabled ON public.cron_jobs USING btree (shop_id, enabled);



CREATE INDEX ix_discovered_urls_last_seen_run_id ON public.discovered_urls USING btree (last_seen_run_id);



CREATE INDEX ix_discovered_urls_shop_book_id ON public.discovered_urls USING btree (shop_book_id);



CREATE INDEX ix_discovered_urls_shop_type_fail ON public.discovered_urls USING btree (shop_id, url_type, fail_count);



CREATE INDEX ix_prices_scrape_run_id ON public.prices USING btree (scrape_run_id);



CREATE INDEX ix_scrape_failures_lifecycle_open ON public.scrape_failures USING btree (lifecycle_state) WHERE (lifecycle_state <> 'acknowledged'::public.validation_lifecycle);



CREATE INDEX ix_scrape_failures_occurred_at ON public.scrape_failures USING btree (occurred_at DESC);



CREATE INDEX ix_scrape_failures_run_bucket ON public.scrape_failures USING btree (run_id, error_reason, http_status);



CREATE INDEX ix_scrape_failures_shop_url ON public.scrape_failures USING btree (shop_id, url);



CREATE INDEX ix_scrape_run_events_run_created ON public.scrape_run_events USING btree (run_id, created_at);



CREATE INDEX ix_scrape_run_events_run_id ON public.scrape_run_events USING btree (run_id);



CREATE INDEX ix_scrape_url_items_run_done_at ON public.scrape_url_items USING btree (run_id, done_at);



CREATE INDEX ix_scrape_url_items_run_status ON public.scrape_url_items USING btree (run_id, status);



CREATE INDEX ix_scrape_url_items_shop_claimed_at ON public.scrape_url_items USING btree (shop_id, claimed_at);



CREATE INDEX ix_shop_authors_canonical_author_id ON public.shop_authors USING btree (canonical_author_id);



CREATE UNIQUE INDEX ix_shop_authors_normalized_name ON public.shop_authors USING btree (normalized_name);



CREATE INDEX ix_shop_book_authors_author_id ON public.shop_book_authors USING btree (author_id);



CREATE INDEX ix_shop_book_changes_shop_book_id ON public.shop_book_changes USING btree (shop_book_id);



CREATE INDEX ix_shop_book_field_updates_shop_book_field ON public.shop_book_field_updates USING btree (shop_book_id, field);



CREATE INDEX ix_shop_books_book_id ON public.shop_books USING btree (book_id);



CREATE INDEX ix_shop_books_created_run_id ON public.shop_books USING btree (created_run_id);



CREATE INDEX ix_url_classifications_book_score ON public.url_classifications USING btree (book_score);



CREATE INDEX ix_url_classifications_is_book_product ON public.url_classifications USING btree (is_book_product);



CREATE INDEX ix_validation_issues_discovered_url_id ON public.validation_issues USING btree (discovered_url_id);



CREATE INDEX ix_validation_issues_lifecycle_state ON public.validation_issues USING btree (lifecycle_state);



CREATE INDEX ix_validation_issues_scrape_run_id ON public.validation_issues USING btree (last_seen_run_id);



CREATE INDEX ix_validation_issues_shop_book_id ON public.validation_issues USING btree (shop_book_id);



CREATE INDEX ix_vi_shop_id_lifecycle ON public.validation_issues USING btree (shop_id, lifecycle_state);



CREATE UNIQUE INDEX uix_vi_discovered_url_field_issue ON public.validation_issues USING btree (discovered_url_id, field, issue) WHERE (discovered_url_id IS NOT NULL);



CREATE UNIQUE INDEX uix_vi_shop_book_field_issue ON public.validation_issues USING btree (shop_book_id, field, issue) WHERE (shop_book_id IS NOT NULL);



CREATE UNIQUE INDEX uix_vi_url_field_issue ON public.validation_issues USING btree (url, field, issue) WHERE ((shop_book_id IS NULL) AND (discovered_url_id IS NULL));



CREATE UNIQUE INDEX uq_shop_books_shop_sku ON public.shop_books USING btree (shop_id, sku) WHERE (sku IS NOT NULL);



ALTER TABLE ONLY public.book_authors
    ADD CONSTRAINT book_authors_author_id_fkey FOREIGN KEY (author_id) REFERENCES public.authors(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.book_authors
    ADD CONSTRAINT book_authors_book_id_fkey FOREIGN KEY (book_id) REFERENCES public.books(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.book_isbns
    ADD CONSTRAINT book_isbns_book_id_fkey FOREIGN KEY (book_id) REFERENCES public.books(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.books
    ADD CONSTRAINT books_publisher_id_fkey FOREIGN KEY (publisher_id) REFERENCES public.publishers(id) ON DELETE SET NULL;



ALTER TABLE ONLY public.books
    ADD CONSTRAINT books_series_id_fkey FOREIGN KEY (series_id) REFERENCES public.series(id) ON DELETE SET NULL;



ALTER TABLE ONLY public.books
    ADD CONSTRAINT books_source_run_id_fkey FOREIGN KEY (source_run_id) REFERENCES public.scrape_runs(id) ON DELETE SET NULL;



ALTER TABLE ONLY public.categories
    ADD CONSTRAINT categories_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.categories(id);



ALTER TABLE ONLY public.cron_jobs
    ADD CONSTRAINT cron_jobs_shop_id_fkey FOREIGN KEY (shop_id) REFERENCES public.shops(id);



ALTER TABLE ONLY public.discovered_urls
    ADD CONSTRAINT discovered_urls_last_seen_run_id_fkey FOREIGN KEY (last_seen_run_id) REFERENCES public.scrape_runs(id);



ALTER TABLE ONLY public.discovered_urls
    ADD CONSTRAINT discovered_urls_listing_id_fkey FOREIGN KEY (shop_book_id) REFERENCES public.shop_books(id);



ALTER TABLE ONLY public.discovered_urls
    ADD CONSTRAINT discovered_urls_shop_id_fkey FOREIGN KEY (shop_id) REFERENCES public.shops(id);



ALTER TABLE ONLY public.cron_jobs
    ADD CONSTRAINT fk_cron_jobs_chain_to_job_id FOREIGN KEY (chain_to_job_id) REFERENCES public.cron_jobs(id) ON DELETE SET NULL;



ALTER TABLE ONLY public.validation_issues
    ADD CONSTRAINT fk_vi_first_seen_run_id FOREIGN KEY (first_seen_run_id) REFERENCES public.scrape_runs(id);



ALTER TABLE ONLY public.validation_issues
    ADD CONSTRAINT fk_vi_shop_id FOREIGN KEY (shop_id) REFERENCES public.shops(id);



ALTER TABLE ONLY public.shop_book_attributes
    ADD CONSTRAINT listing_attributes_listing_id_fkey FOREIGN KEY (shop_book_id) REFERENCES public.shop_books(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.shop_book_authors
    ADD CONSTRAINT listing_authors_author_id_fkey FOREIGN KEY (author_id) REFERENCES public.shop_authors(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.shop_book_authors
    ADD CONSTRAINT listing_authors_listing_id_fkey FOREIGN KEY (shop_book_id) REFERENCES public.shop_books(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.shop_book_changes
    ADD CONSTRAINT listing_changes_listing_id_fkey FOREIGN KEY (shop_book_id) REFERENCES public.shop_books(id);



ALTER TABLE ONLY public.shop_book_changes
    ADD CONSTRAINT listing_changes_scrape_run_id_fkey FOREIGN KEY (scrape_run_id) REFERENCES public.scrape_runs(id);



ALTER TABLE ONLY public.shop_book_field_updates
    ADD CONSTRAINT listing_field_updates_listing_id_fkey FOREIGN KEY (shop_book_id) REFERENCES public.shop_books(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.shop_books
    ADD CONSTRAINT listings_last_run_id_fkey FOREIGN KEY (last_run_id) REFERENCES public.scrape_runs(id);



ALTER TABLE ONLY public.shop_books
    ADD CONSTRAINT listings_shop_id_fkey FOREIGN KEY (shop_id) REFERENCES public.shops(id);



ALTER TABLE ONLY public.prices
    ADD CONSTRAINT prices_listing_id_fkey FOREIGN KEY (shop_book_id) REFERENCES public.shop_books(id);



ALTER TABLE ONLY public.prices
    ADD CONSTRAINT prices_scrape_run_id_fkey FOREIGN KEY (scrape_run_id) REFERENCES public.scrape_runs(id);



ALTER TABLE ONLY public.scrape_run_events
    ADD CONSTRAINT run_events_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.scrape_runs(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.scrape_failures
    ADD CONSTRAINT scrape_failures_discovered_url_id_fkey FOREIGN KEY (discovered_url_id) REFERENCES public.discovered_urls(id);



ALTER TABLE ONLY public.scrape_failures
    ADD CONSTRAINT scrape_failures_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.scrape_runs(id);



ALTER TABLE ONLY public.scrape_failures
    ADD CONSTRAINT scrape_failures_scrape_url_item_id_fkey FOREIGN KEY (scrape_url_item_id) REFERENCES public.scrape_url_items(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.scrape_failures
    ADD CONSTRAINT scrape_failures_shop_id_fkey FOREIGN KEY (shop_id) REFERENCES public.shops(id);



ALTER TABLE ONLY public.scrape_runs
    ADD CONSTRAINT scrape_runs_shop_id_fkey FOREIGN KEY (shop_id) REFERENCES public.shops(id);



ALTER TABLE ONLY public.scrape_url_items
    ADD CONSTRAINT scrape_url_items_discovered_url_id_fkey FOREIGN KEY (discovered_url_id) REFERENCES public.discovered_urls(id);



ALTER TABLE ONLY public.scrape_url_items
    ADD CONSTRAINT scrape_url_items_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.scrape_runs(id);



ALTER TABLE ONLY public.scrape_url_items
    ADD CONSTRAINT scrape_url_items_shop_id_fkey FOREIGN KEY (shop_id) REFERENCES public.shops(id);



ALTER TABLE ONLY public.shop_authors
    ADD CONSTRAINT shop_authors_canonical_author_id_fkey FOREIGN KEY (canonical_author_id) REFERENCES public.authors(id) ON DELETE SET NULL;



ALTER TABLE ONLY public.shop_books
    ADD CONSTRAINT shop_books_book_id_fkey FOREIGN KEY (book_id) REFERENCES public.books(id) ON DELETE SET NULL;



ALTER TABLE ONLY public.shop_books
    ADD CONSTRAINT shop_books_created_run_id_fkey FOREIGN KEY (created_run_id) REFERENCES public.scrape_runs(id);



ALTER TABLE ONLY public.shop_settings
    ADD CONSTRAINT shop_settings_shop_id_fkey FOREIGN KEY (shop_id) REFERENCES public.shops(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.url_classifications
    ADD CONSTRAINT url_classifications_discovered_url_id_fkey FOREIGN KEY (discovered_url_id) REFERENCES public.discovered_urls(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.validation_issues
    ADD CONSTRAINT validation_issues_discovered_url_id_fkey FOREIGN KEY (discovered_url_id) REFERENCES public.discovered_urls(id);



ALTER TABLE ONLY public.validation_issues
    ADD CONSTRAINT validation_issues_listing_id_fkey FOREIGN KEY (shop_book_id) REFERENCES public.shop_books(id);



ALTER TABLE ONLY public.validation_issues
    ADD CONSTRAINT validation_issues_scrape_run_id_fkey FOREIGN KEY (last_seen_run_id) REFERENCES public.scrape_runs(id);
