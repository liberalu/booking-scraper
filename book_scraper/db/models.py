from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    text as sa_text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id"), nullable=True
    )

    parent: Mapped["Category | None"] = relationship(remote_side="Category.id")


class Shop(Base):
    __tablename__ = "shops"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    base_url: Mapped[str] = mapped_column(String, nullable=False)

    shop_books: Mapped[list["ShopBook"]] = relationship(back_populates="shop")
    settings: Mapped[list["ShopSettings"]] = relationship(
        back_populates="shop", cascade="all, delete-orphan"
    )


class ShopSettings(Base):
    __tablename__ = "shop_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shop_id: Mapped[int] = mapped_column(
        ForeignKey("shops.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False, default="str")

    shop: Mapped["Shop"] = relationship(back_populates="settings")

    __table_args__ = (
        UniqueConstraint("shop_id", "key", name="uq_shop_settings_shop_key"),
    )


match_status_enum = Enum(
    "unmatched", "matched", "uncertain", name="match_status", create_type=True
)
match_method_enum = Enum(
    "isbn", "fuzzy", "manual", name="match_method", create_type=True
)

shop_book_type_enum = Enum(
    "book", "non_book", "audio", "ebook", name="shop_book_type", create_type=False
)


class ShopBook(Base):
    __tablename__ = "shop_books"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)

    # Core product data (always present)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    author: Mapped[str | None] = mapped_column(Text, nullable=True)
    sku: Mapped[str | None] = mapped_column(String, nullable=True)
    isbn: Mapped[str | None] = mapped_column(String, nullable=True)

    # Common metadata
    publisher: Mapped[str | None] = mapped_column(String, nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    format: Mapped[str | None] = mapped_column(String, nullable=True)
    type: Mapped[str] = mapped_column(
        shop_book_type_enum, nullable=False, server_default="book"
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    categories: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)

    # Pricing (latest snapshot, also stored in prices table)
    price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    price_original: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    in_stock: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Matching
    match_status: Mapped[str] = mapped_column(
        match_status_enum, nullable=False, default="unmatched"
    )
    match_method: Mapped[str | None] = mapped_column(match_method_enum, nullable=True)

    # Run tracking
    last_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("scrape_runs.id"), nullable=True
    )
    last_run_action: Mapped[str | None] = mapped_column(String, nullable=True)

    # Lifecycle
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    inactive_since: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )

    __table_args__ = (UniqueConstraint("shop_id", "url", name="uq_shop_book_shop_url"),)

    shop: Mapped["Shop"] = relationship(back_populates="shop_books")
    prices: Mapped[list["Price"]] = relationship(back_populates="shop_book")
    changes: Mapped[list["ShopBookChange"]] = relationship(back_populates="shop_book")
    attributes: Mapped[list["ShopBookAttribute"]] = relationship(
        back_populates="shop_book",
        cascade="all, delete-orphan",
    )
    discovered_urls: Mapped[list["DiscoveredUrl"]] = relationship(
        back_populates="shop_book"
    )
    authors: Mapped[list["ShopAuthor"]] = relationship(
        secondary="shop_book_authors",
        order_by="ShopBookAuthor.position",
        viewonly=True,
    )


class ShopAuthor(Base):
    """Deduplicated author catalogue across shops.

    Matched by `normalized_name` (lower-cased, whitespace-collapsed)
    so "L. Šernienė" and " l. šernienė " resolve to the same row.
    """

    __tablename__ = "shop_authors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class ShopBookAuthor(Base):
    """Join between shop_books and shop_authors with ordering preserved."""

    __tablename__ = "shop_book_authors"

    shop_book_id: Mapped[int] = mapped_column(
        ForeignKey("shop_books.id", ondelete="CASCADE"), primary_key=True
    )
    author_id: Mapped[int] = mapped_column(
        ForeignKey("shop_authors.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ShopBookAttribute(Base):
    __tablename__ = "shop_book_attributes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shop_book_id: Mapped[int] = mapped_column(
        ForeignKey("shop_books.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "shop_book_id", "key", name="uq_shop_book_attribute_shop_book_key"
        ),
    )

    shop_book: Mapped["ShopBook"] = relationship(back_populates="attributes")


class ShopBookFieldUpdate(Base):
    """Per-field last-changed timestamp on a shop_book.

    One row per (shop_book_id, field) for the handful of fields we track
    (price, description, image_url, author, isbn, publisher, year,
    format). Updated only when the scrape actually sees a new value.
    """

    __tablename__ = "shop_book_field_updates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shop_book_id: Mapped[int] = mapped_column(
        ForeignKey("shop_books.id", ondelete="CASCADE"), nullable=False
    )
    field: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "shop_book_id",
            "field",
            name="uq_shop_book_field_updates_shop_book_field",
        ),
        Index(
            "ix_shop_book_field_updates_shop_book_field",
            "shop_book_id",
            "field",
        ),
    )


class Price(Base):
    __tablename__ = "prices"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    shop_book_id: Mapped[int] = mapped_column(
        ForeignKey("shop_books.id"), nullable=False
    )
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    price_original: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    in_stock: Mapped[bool] = mapped_column(Boolean, nullable=False)
    scraped_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    scrape_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("scrape_runs.id"), nullable=True, index=True
    )
    discount_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2),
        Computed(
            "CASE WHEN price_original IS NOT NULL AND price_original > 0 "
            "THEN ROUND((1 - price / price_original) * 100, 2) END"
        ),
    )

    shop_book: Mapped["ShopBook"] = relationship(back_populates="prices")


class ShopBookChange(Base):
    __tablename__ = "shop_book_changes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    shop_book_id: Mapped[int] = mapped_column(
        ForeignKey("shop_books.id"), nullable=False, index=True
    )
    scrape_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("scrape_runs.id"), nullable=True
    )
    field: Mapped[str] = mapped_column(String, nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    shop_book: Mapped["ShopBook"] = relationship(back_populates="changes")


discovery_source_enum = Enum(
    "sitemap",
    "category",
    "full_crawl",
    name="discovery_source",
    create_type=False,
)

url_type_enum = Enum(
    "unknown",
    "product",
    "non_product",
    name="url_type",
    create_type=False,
)

scrape_phase_enum = Enum(
    "discover_sitemap",
    "discover_categories",
    "discover_full_crawl",
    "scan",
    name="scrape_phase",
    create_type=False,
)

scrape_status_enum = Enum(
    "running",
    # Operator-requested stop is in flight: the spider's heartbeat tick
    # observes this transition and exits cleanly. The spider's `closed()`
    # flips the row to `failed` with `error_reason='stopped_by_operator'`,
    # so `stopping` is always transient.
    "stopping",
    # Operator-requested pause: the spider's heartbeat observes this and
    # spins in a poll loop. The heartbeat keeps ticking (preventing reaper
    # from killing the run). Resume via POST /api/runs/{id}/resume.
    "paused",
    "completed",
    "failed",
    name="scrape_status",
    create_type=False,
)

validation_lifecycle_enum = Enum(
    "new",
    "recurring",
    "already_seen",
    name="validation_lifecycle",
    create_type=False,
)


class DiscoveredUrl(Base):
    __tablename__ = "discovered_urls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_url: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(discovery_source_enum, nullable=False)
    url_type: Mapped[str] = mapped_column(
        url_type_enum, nullable=False, server_default="unknown"
    )
    fail_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    last_seen_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("scrape_runs.id"), nullable=True
    )
    shop_book_id: Mapped[int | None] = mapped_column(
        ForeignKey("shop_books.id"), nullable=True
    )

    shop: Mapped["Shop"] = relationship()
    shop_book: Mapped["ShopBook | None"] = relationship(
        back_populates="discovered_urls"
    )
    last_seen_run: Mapped["ScrapeRun | None"] = relationship()
    classification: Mapped["UrlClassification | None"] = relationship(
        back_populates="discovered_url", uselist=False
    )

    __table_args__ = (
        UniqueConstraint(
            "shop_id", "normalized_url", name="uq_discovered_urls_shop_normalized"
        ),
        Index("ix_discovered_urls_shop_type_fail", "shop_id", "url_type", "fail_count"),
        Index("ix_discovered_urls_shop_book_id", "shop_book_id"),
        Index("ix_discovered_urls_last_seen_run_id", "last_seen_run_id"),
    )


class UrlClassification(Base):
    __tablename__ = "url_classifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    discovered_url_id: Mapped[int] = mapped_column(
        ForeignKey("discovered_urls.id"), nullable=False, unique=True
    )
    book_score: Mapped[int] = mapped_column(Integer, nullable=False)
    is_book_product: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reasons: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    classified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    discovered_url: Mapped["DiscoveredUrl"] = relationship(
        back_populates="classification"
    )

    __table_args__ = (
        Index("ix_url_classifications_book_score", "book_score"),
        Index("ix_url_classifications_is_book_product", "is_book_product"),
    )


class ScrapeRun(Base):
    __tablename__ = "scrape_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), nullable=False)
    phase: Mapped[str] = mapped_column(scrape_phase_enum, nullable=False)
    status: Mapped[str] = mapped_column(scrape_status_enum, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    urls_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    urls_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    items_added: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    items_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errors_4xx: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errors_5xx: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_heartbeat: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Why the run terminated. Stamped at finalize for every code path that
    # transitions a run to completed/failed (Scrapy `closed(reason)`,
    # StallDetector, dashboard reaper, manual kill, boot reconciliation).
    # Examples: "finished", "shutdown", "stall_timeout", "heartbeat_timeout",
    # "orphan_on_boot", "stale_pre_scan", "killed_pid_dead". Null on legacy
    # rows that finalized before this column existed.
    close_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # When a run is reaped for heartbeat_timeout / stall_timeout, its
    # pending scrape_url_items are still useful — the next scheduled run
    # inherits them rather than discarding the work. This flag is set by
    # the reaper / StallDetector on the failed-but-resumable transition.
    resumable_after_failure: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=sa_text("false")
    )

    shop: Mapped["Shop"] = relationship()
    validation_issues: Mapped[list["ValidationIssue"]] = relationship(
        back_populates="scrape_run"
    )


scrape_url_status_enum = Enum(
    "pending",
    "processing",
    "done",
    "failed",
    name="scrape_url_status",
    create_type=False,
)


class ScrapeUrlItem(Base):
    """Persistent work-queue item for the scan spider.

    Written by ScanService.prepare_scan() before scraping begins.
    Allows the spider to resume after a crash: any 'processing' rows
    from a previous run are reset to 'pending' on next start.
    """

    __tablename__ = "scrape_url_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("scrape_runs.id"), nullable=False)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), nullable=False)
    discovered_url_id: Mapped[int | None] = mapped_column(
        ForeignKey("discovered_urls.id"), nullable=True
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    url_type: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="product"
    )
    status: Mapped[str] = mapped_column(
        scrape_url_status_enum, nullable=False, server_default="pending"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    done_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_delay_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    delay_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    response_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        Index("ix_scrape_url_items_run_status", "run_id", "status"),
        Index("ix_scrape_url_items_shop_claimed_at", "shop_id", "claimed_at"),
        Index("ix_scrape_url_items_run_done_at", "run_id", "done_at"),
        UniqueConstraint("run_id", "url", name="uq_scrape_url_items_run_url"),
    )


class ValidationIssue(Base):
    __tablename__ = "validation_issues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scrape_run_id: Mapped[int] = mapped_column(
        ForeignKey("scrape_runs.id"), nullable=False, index=True
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    field: Mapped[str] = mapped_column(String, nullable=False)
    issue: Mapped[str] = mapped_column(String, nullable=False)
    raw_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    shop_book_id: Mapped[int | None] = mapped_column(
        ForeignKey("shop_books.id"), nullable=True, index=True
    )
    discovered_url_id: Mapped[int | None] = mapped_column(
        ForeignKey("discovered_urls.id"), nullable=True, index=True
    )
    lifecycle_state: Mapped[str] = mapped_column(
        validation_lifecycle_enum,
        nullable=False,
        server_default="new",
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "NOT (shop_book_id IS NOT NULL AND discovered_url_id IS NOT NULL)",
            name="ck_validation_issues_single_entity",
        ),
        Index(
            "ix_validation_issues_lifecycle_state",
            "lifecycle_state",
        ),
    )

    scrape_run: Mapped["ScrapeRun"] = relationship(back_populates="validation_issues")
    shop_book: Mapped["ShopBook | None"] = relationship()
    discovered_url: Mapped["DiscoveredUrl | None"] = relationship()


class CronJob(Base):
    """Scheduled scrape job. Read by scripts/generate_crontab.py at scraper boot."""

    __tablename__ = "cron_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), nullable=False)
    phase: Mapped[str] = mapped_column(Text, nullable=False)
    strategy: Mapped[str | None] = mapped_column(Text, nullable=True)
    args: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    cron_expression: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sa_text("true")
    )
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    shop: Mapped["Shop"] = relationship()

    __table_args__ = (Index("ix_cron_jobs_shop_enabled", "shop_id", "enabled"),)
