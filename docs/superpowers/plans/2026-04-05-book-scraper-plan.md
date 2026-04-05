# Book Price Scraper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Scrapy-based multi-shop book price scraper with PostgreSQL storage, starting with vaga.lt as the first shop.

**Architecture:** Scrapy project with per-shop spider directories, shared item pipelines for PostgreSQL storage, Alembic for migrations. Each pipeline phase (discover, scan, prices) is a separate spider. Non-scraping operations (change detection, matching, status) are Scrapy custom commands.

**Tech Stack:** Scrapy, SQLAlchemy 2.0, Alembic, PostgreSQL, Pydantic, uv, Ruff, mypy, pytest

**Spec:** `docs/superpowers/specs/2026-04-05-book-scraper-design.md`

---

## File Structure

```
_prototypes/                        # existing scripts moved here
scrapy.cfg                          # Scrapy deploy config
pyproject.toml                      # uv project config (rewritten for Scrapy)
book_scraper/
    __init__.py
    settings.py                     # Scrapy settings
    items.py                        # ListingItem, PriceItem
    middlewares.py                  # (default Scrapy template)
    pipelines.py                    # ValidationPipeline, PostgresPipeline
    db/
        __init__.py
        models.py                   # SQLAlchemy ORM models
        session.py                  # engine + session factory
        repo.py                     # CRUD operations
    spiders/
        __init__.py
        vaga/
            __init__.py
            discover.py             # Phase 1: sitemap spider
            scan.py                 # Phase 3: full product spider
            prices.py               # Phase 4: price-only spider
    matching/
        __init__.py
        matcher.py
        isbn.py
        fuzzy.py
    commands/
        __init__.py
        changes.py
        match.py
        status.py
alembic/
    env.py
    versions/
        001_initial_schema.py
alembic.ini
tests/
    __init__.py
    conftest.py
    fixtures/
        vaga_sitemap.xml
        vaga_category_page.html
        vaga_product_page.html
    test_vaga_parsers.py
    test_items.py
    test_db_repo.py
```

---

### Task 1: Move existing files to _prototypes/ and reset project

**Files:**
- Create: `_prototypes/` (move all existing scripts here)
- Delete: `src/book_scraper/` (old scaffolded code)
- Delete: `tests/` (old tests)
- Modify: `pyproject.toml` (rewrite for Scrapy)

- [ ] **Step 1: Create _prototypes/ and move existing files**

```bash
mkdir -p _prototypes
mv scrape_book.py scrape_book_curl.py scrape_book_fast.py scrape_prices.py \
   scrape_sitemap.py scrape_autocomplete.py scrape_autocomplete_fast.py \
   dump_html.py dump_html2.py test_cookie_reuse.py test_curl_cffi.py \
   test_curl_cffi2.py test_parallel_playwright.py deploy.sh Dockerfile \
   book_urls.txt page_dump.html page_dump2.html page_screenshot.png \
   prices.csv prices_auto.csv _prototypes/
```

- [ ] **Step 2: Remove old scaffolded code**

```bash
rm -rf src/ tests/ .venv/
```

- [ ] **Step 3: Rewrite pyproject.toml**

```toml
[project]
name = "book-scraper"
version = "0.1.0"
description = "Multi-shop book price scraper for Lithuanian e-shops"
requires-python = ">=3.12"
dependencies = [
    "Scrapy>=2.12",
    "scrapy-impersonate>=1.6",
    "pydantic>=2.0",
    "SQLAlchemy[asyncio]>=2.0",
    "asyncpg>=0.30",
    "alembic>=1.15",
    "psycopg2-binary>=2.9",
]

[project.optional-dependencies]
dev = [
    "ruff>=0.11",
    "mypy>=1.15",
    "pytest>=8.0",
    "pytest-asyncio>=0.25",
]

[tool.ruff]
line-length = 88
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "UP", "B", "SIM"]

[tool.mypy]
strict = true
python_version = "3.12"

[tool.pytest.ini_options]
testpaths = ["tests"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["book_scraper"]
```

- [ ] **Step 4: Install dependencies**

```bash
uv sync --all-extras
```

Expected: all packages install successfully, `.venv/` created.

- [ ] **Step 5: Commit**

```bash
git init
git add -A
git commit -m "chore: move prototypes to _prototypes/, reset project for Scrapy"
```

---

### Task 2: Scrapy project skeleton

**Files:**
- Create: `scrapy.cfg`
- Create: `book_scraper/__init__.py`
- Create: `book_scraper/settings.py`
- Create: `book_scraper/items.py`
- Create: `book_scraper/middlewares.py`
- Create: `book_scraper/pipelines.py`
- Create: `book_scraper/spiders/__init__.py`

- [ ] **Step 1: Create scrapy.cfg**

```ini
[settings]
default = book_scraper.settings

[deploy]
project = book_scraper
```

- [ ] **Step 2: Create book_scraper/__init__.py**

```python
```

(empty file)

- [ ] **Step 3: Create book_scraper/settings.py**

```python
BOT_NAME = "book_scraper"

SPIDER_MODULES = ["book_scraper.spiders"]
NEWSPIDER_MODULE = "book_scraper.spiders"

# Required for scrapy-impersonate and scrapy-playwright
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"

ROBOTSTXT_OBEY = True

CONCURRENT_REQUESTS_PER_DOMAIN = 1
DOWNLOAD_DELAY = 1

FEED_EXPORT_ENCODING = "utf-8"

# Item pipelines (enabled later when DB is set up)
# ITEM_PIPELINES = {
#     "book_scraper.pipelines.ValidationPipeline": 100,
#     "book_scraper.pipelines.PostgresPipeline": 200,
# }

# Database connection
DATABASE_URL = "postgresql+asyncpg://localhost:5432/book_scraper"
```

- [ ] **Step 4: Create book_scraper/items.py**

```python
import scrapy


class ListingItem(scrapy.Item):
    """Full product data from a shop."""

    url = scrapy.Field()
    shop_name = scrapy.Field()
    shop_title = scrapy.Field()
    shop_author = scrapy.Field()
    isbn = scrapy.Field()
    publisher = scrapy.Field()
    year = scrapy.Field()
    pages = scrapy.Field()
    cover_type = scrapy.Field()
    description = scrapy.Field()
    image_url = scrapy.Field()
    price = scrapy.Field()
    price_original = scrapy.Field()
    in_stock = scrapy.Field()
    categories = scrapy.Field()


class PriceItem(scrapy.Item):
    """Lightweight price-only data for re-scraping."""

    url = scrapy.Field()
    shop_name = scrapy.Field()
    price = scrapy.Field()
    price_original = scrapy.Field()
    in_stock = scrapy.Field()


class DiscoveredUrlItem(scrapy.Item):
    """A URL found during discovery phase."""

    url = scrapy.Field()
    shop_name = scrapy.Field()
```

- [ ] **Step 5: Create book_scraper/middlewares.py**

```python
from scrapy import signals


class BookScraperSpiderMiddleware:
    @classmethod
    def from_crawler(cls, crawler):
        s = cls()
        crawler.signals.connect(s.spider_opened, signal=signals.spider_opened)
        return s

    def process_spider_input(self, response, spider):
        return None

    def process_spider_output(self, response, result, spider):
        for i in result:
            yield i

    def process_spider_exception(self, response, exception, spider):
        pass

    def spider_opened(self, spider):
        spider.logger.info("Spider opened: %s" % spider.name)
```

- [ ] **Step 6: Create book_scraper/pipelines.py (stub)**

```python
class ValidationPipeline:
    def process_item(self, item, spider):
        return item


class PostgresPipeline:
    def process_item(self, item, spider):
        return item
```

- [ ] **Step 7: Create book_scraper/spiders/__init__.py**

```python
```

(empty file)

- [ ] **Step 8: Verify Scrapy project works**

```bash
uv run scrapy list
```

Expected: empty output (no spiders yet), no errors.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "feat: add Scrapy project skeleton"
```

---

### Task 3: Database models and Alembic migration

**Files:**
- Create: `book_scraper/db/__init__.py`
- Create: `book_scraper/db/models.py`
- Create: `book_scraper/db/session.py`
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/versions/001_initial_schema.py`

- [ ] **Step 1: Create book_scraper/db/__init__.py**

```python
```

(empty file)

- [ ] **Step 2: Create book_scraper/db/models.py**

```python
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Computed,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Book(Base):
    __tablename__ = "books"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    isbn: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    author: Mapped[str | None] = mapped_column(Text, nullable=True)
    publisher: Mapped[str | None] = mapped_column(String, nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    language: Mapped[str] = mapped_column(String, nullable=False, default="lt")
    format: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    labels: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )

    listings: Mapped[list["Listing"]] = relationship(back_populates="book")
    categories: Mapped[list["Category"]] = relationship(
        secondary="book_categories", back_populates="books"
    )


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id"), nullable=True
    )

    parent: Mapped["Category | None"] = relationship(remote_side="Category.id")
    books: Mapped[list["Book"]] = relationship(
        secondary="book_categories", back_populates="categories"
    )


class BookCategory(Base):
    __tablename__ = "book_categories"

    book_id: Mapped[int] = mapped_column(
        ForeignKey("books.id"), primary_key=True
    )
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id"), primary_key=True
    )


class Shop(Base):
    __tablename__ = "shops"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    base_url: Mapped[str] = mapped_column(String, nullable=False)

    listings: Mapped[list["Listing"]] = relationship(back_populates="shop")


class MatchStatus(str, Enum):
    pass


match_status_enum = Enum(
    "unmatched", "matched", "uncertain", name="match_status", create_type=True
)
match_method_enum = Enum(
    "isbn", "fuzzy", "manual", name="match_method", create_type=True
)


class Listing(Base):
    __tablename__ = "listings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    book_id: Mapped[int | None] = mapped_column(
        ForeignKey("books.id"), nullable=True
    )
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    shop_title: Mapped[str] = mapped_column(Text, nullable=False)
    shop_author: Mapped[str | None] = mapped_column(Text, nullable=True)
    isbn_from_shop: Mapped[str | None] = mapped_column(String, nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    match_status: Mapped[str] = mapped_column(
        match_status_enum, nullable=False, default="unmatched"
    )
    match_method: Mapped[str | None] = mapped_column(
        match_method_enum, nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )

    __table_args__ = (UniqueConstraint("shop_id", "url", name="uq_listing_shop_url"),)

    book: Mapped["Book | None"] = relationship(back_populates="listings")
    shop: Mapped["Shop"] = relationship(back_populates="listings")
    prices: Mapped[list["Price"]] = relationship(back_populates="listing")


class Price(Base):
    __tablename__ = "prices"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    listing_id: Mapped[int] = mapped_column(
        ForeignKey("listings.id"), nullable=False
    )
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    price_original: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    in_stock: Mapped[bool] = mapped_column(Boolean, nullable=False)
    scraped_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    discount_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2),
        Computed(
            "CASE WHEN price_original IS NOT NULL AND price_original > 0 "
            "THEN ROUND((1 - price / price_original) * 100, 2) END"
        ),
    )

    listing: Mapped["Listing"] = relationship(back_populates="prices")
```

- [ ] **Step 3: Create book_scraper/db/session.py**

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


def get_engine(database_url: str):
    # Use sync engine for Scrapy pipelines (Scrapy runs in Twisted reactor)
    sync_url = database_url.replace("postgresql+asyncpg", "postgresql+psycopg2")
    return create_engine(sync_url)


def get_session_factory(database_url: str) -> sessionmaker[Session]:
    engine = get_engine(database_url)
    return sessionmaker(bind=engine)
```

- [ ] **Step 4: Create alembic.ini**

```ini
[alembic]
script_location = alembic
sqlalchemy.url = postgresql+psycopg2://localhost:5432/book_scraper

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

- [ ] **Step 5: Create alembic/env.py**

```python
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from book_scraper.db.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 6: Create initial migration**

```bash
mkdir -p alembic/versions
uv run alembic revision --autogenerate -m "initial schema"
```

Expected: migration file created in `alembic/versions/`.

- [ ] **Step 7: Verify migration can be applied**

Requires a running PostgreSQL. Create the database first:

```bash
createdb book_scraper
uv run alembic upgrade head
```

Expected: all tables created (books, categories, book_categories, shops, listings, prices).

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat: add SQLAlchemy models and Alembic migration"
```

---

### Task 4: DB repository and tests

**Files:**
- Create: `book_scraper/db/repo.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/test_db_repo.py`

- [ ] **Step 1: Create tests/__init__.py**

```python
```

(empty file)

- [ ] **Step 2: Create tests/conftest.py**

```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from book_scraper.db.models import Base

TEST_DATABASE_URL = "postgresql+psycopg2://localhost:5432/book_scraper_test"


@pytest.fixture(scope="session")
def engine():
    engine = create_engine(TEST_DATABASE_URL)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture()
def db_session(engine):
    connection = engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection)()
    yield session
    session.close()
    transaction.rollback()
    connection.close()
```

- [ ] **Step 3: Write failing test for repo.upsert_shop**

```python
# tests/test_db_repo.py
from book_scraper.db.repo import upsert_shop


def test_upsert_shop_creates_new(db_session):
    shop = upsert_shop(db_session, name="vaga", base_url="https://vaga.lt")
    assert shop.id is not None
    assert shop.name == "vaga"
    assert shop.base_url == "https://vaga.lt"


def test_upsert_shop_returns_existing(db_session):
    shop1 = upsert_shop(db_session, name="vaga", base_url="https://vaga.lt")
    shop2 = upsert_shop(db_session, name="vaga", base_url="https://vaga.lt")
    assert shop1.id == shop2.id
```

- [ ] **Step 4: Run test to verify it fails**

```bash
createdb book_scraper_test 2>/dev/null; uv run pytest tests/test_db_repo.py -v
```

Expected: FAIL with `ImportError: cannot import name 'upsert_shop'`

- [ ] **Step 5: Create book_scraper/db/repo.py**

```python
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from book_scraper.db.models import Book, Category, Listing, Price, Shop


def upsert_shop(session: Session, name: str, base_url: str) -> Shop:
    stmt = select(Shop).where(Shop.name == name)
    shop = session.execute(stmt).scalar_one_or_none()
    if shop is None:
        shop = Shop(name=name, base_url=base_url)
        session.add(shop)
        session.flush()
    return shop


def upsert_listing(
    session: Session,
    shop_id: int,
    url: str,
    shop_title: str,
    shop_author: str | None = None,
    isbn_from_shop: str | None = None,
    image_url: str | None = None,
) -> Listing:
    stmt = select(Listing).where(Listing.shop_id == shop_id, Listing.url == url)
    listing = session.execute(stmt).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if listing is None:
        listing = Listing(
            shop_id=shop_id,
            url=url,
            shop_title=shop_title,
            shop_author=shop_author,
            isbn_from_shop=isbn_from_shop,
            image_url=image_url,
            first_seen_at=now,
            last_seen_at=now,
        )
        session.add(listing)
        session.flush()
    else:
        listing.shop_title = shop_title
        listing.shop_author = shop_author
        listing.isbn_from_shop = isbn_from_shop
        listing.image_url = image_url
        listing.last_seen_at = now
        listing.is_active = True
        session.flush()
    return listing


def insert_price(
    session: Session,
    listing_id: int,
    price: Decimal,
    price_original: Decimal | None,
    in_stock: bool,
) -> Price:
    record = Price(
        listing_id=listing_id,
        price=price,
        price_original=price_original,
        in_stock=in_stock,
        scraped_at=datetime.now(timezone.utc),
    )
    session.add(record)
    session.flush()
    return record


def upsert_category(session: Session, name: str, slug: str, parent_id: int | None = None) -> Category:
    stmt = select(Category).where(Category.slug == slug)
    cat = session.execute(stmt).scalar_one_or_none()
    if cat is None:
        cat = Category(name=name, slug=slug, parent_id=parent_id)
        session.add(cat)
        session.flush()
    return cat


def mark_listings_inactive(session: Session, shop_id: int, active_urls: set[str]) -> int:
    """Mark listings not in active_urls as inactive. Returns count of deactivated."""
    stmt = select(Listing).where(Listing.shop_id == shop_id, Listing.is_active.is_(True))
    listings = session.execute(stmt).scalars().all()
    count = 0
    for listing in listings:
        if listing.url not in active_urls:
            listing.is_active = False
            count += 1
    session.flush()
    return count
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
uv run pytest tests/test_db_repo.py -v
```

Expected: 2 tests PASS.

- [ ] **Step 7: Add tests for upsert_listing and insert_price**

Add to `tests/test_db_repo.py`:

```python
from decimal import Decimal

from book_scraper.db.repo import insert_price, upsert_listing, upsert_shop


def test_upsert_listing_creates_new(db_session):
    shop = upsert_shop(db_session, name="vaga", base_url="https://vaga.lt")
    listing = upsert_listing(
        db_session,
        shop_id=shop.id,
        url="https://vaga.lt/test-book",
        shop_title="Test Book",
        shop_author="Author",
        isbn_from_shop="9781234567890",
    )
    assert listing.id is not None
    assert listing.shop_title == "Test Book"
    assert listing.match_status == "unmatched"
    assert listing.is_active is True


def test_upsert_listing_updates_existing(db_session):
    shop = upsert_shop(db_session, name="vaga", base_url="https://vaga.lt")
    listing1 = upsert_listing(
        db_session, shop_id=shop.id, url="https://vaga.lt/book", shop_title="Old"
    )
    listing2 = upsert_listing(
        db_session, shop_id=shop.id, url="https://vaga.lt/book", shop_title="New"
    )
    assert listing1.id == listing2.id
    assert listing2.shop_title == "New"


def test_insert_price(db_session):
    shop = upsert_shop(db_session, name="vaga", base_url="https://vaga.lt")
    listing = upsert_listing(
        db_session, shop_id=shop.id, url="https://vaga.lt/book", shop_title="Book"
    )
    price = insert_price(
        db_session,
        listing_id=listing.id,
        price=Decimal("9.99"),
        price_original=Decimal("14.99"),
        in_stock=True,
    )
    assert price.id is not None
    assert price.price == Decimal("9.99")
    assert price.price_original == Decimal("14.99")
```

- [ ] **Step 8: Run all tests**

```bash
uv run pytest tests/test_db_repo.py -v
```

Expected: 5 tests PASS.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "feat: add DB repository with CRUD operations and tests"
```

---

### Task 5: Save vaga.lt HTML/XML fixtures for parser tests

**Files:**
- Create: `tests/fixtures/vaga_sitemap.xml`
- Create: `tests/fixtures/vaga_category_page.html`
- Create: `tests/fixtures/vaga_product_page.html`

- [ ] **Step 1: Download sitemap fragment**

Save a small representative snippet from `https://vaga.lt/sitemap.xml` (first 5-10 URLs) as `tests/fixtures/vaga_sitemap.xml`. Since the real sitemap has no newlines, save a cleaned-up version with proper formatting for readability.

```bash
curl -s 'https://vaga.lt/sitemap.xml' | python3 -c "
import sys, xml.etree.ElementTree as ET
tree = ET.parse(sys.stdin)
urls = tree.findall('.//{http://www.sitemaps.org/schemas/sitemap/0.9}url')
root = ET.Element('urlset', xmlns='http://www.sitemaps.org/schemas/sitemap/0.9')
for u in urls[:5]:
    root.append(u)
ET.indent(root)
print(ET.tostring(root, encoding='unicode'))
" > tests/fixtures/vaga_sitemap.xml
```

- [ ] **Step 2: Download a category page**

```bash
curl -s 'https://vaga.lt/knygos?limit=100&page=1' > tests/fixtures/vaga_category_page.html
```

Trim to just the product listing section if the file is too large (keep 2-3 product cards).

- [ ] **Step 3: Download a product page**

```bash
curl -s 'https://vaga.lt/sirdies-kauleliai' > tests/fixtures/vaga_product_page.html
```

Pick a product page that has JSON-LD with `@type: Book`, price, ISBN, and HTML property spans.

- [ ] **Step 4: Commit**

```bash
git add tests/fixtures/
git commit -m "test: add vaga.lt HTML/XML fixtures"
```

---

### Task 6: Vaga.lt parsers and tests

**Files:**
- Create: `tests/test_vaga_parsers.py`
- Create: `book_scraper/spiders/vaga/__init__.py`
- Create: `book_scraper/spiders/vaga/parsers.py`

Parser logic lives in a separate `parsers.py` module (not in the spider) so it can be tested without Scrapy.

- [ ] **Step 1: Write failing tests for sitemap parsing**

```python
# tests/test_vaga_parsers.py
from pathlib import Path

from book_scraper.spiders.vaga.parsers import parse_sitemap_urls

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_sitemap_urls():
    xml_content = (FIXTURES / "vaga_sitemap.xml").read_text()
    urls = parse_sitemap_urls(xml_content)
    assert len(urls) > 0
    assert all(url.startswith("https://vaga.lt/") for url in urls)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_vaga_parsers.py::test_parse_sitemap_urls -v
```

Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement parse_sitemap_urls**

```python
# book_scraper/spiders/vaga/parsers.py
import json
import re
import xml.etree.ElementTree as ET


def parse_sitemap_urls(xml_content: str) -> list[str]:
    """Extract all URLs from a vaga.lt sitemap XML string."""
    root = ET.fromstring(xml_content)
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    return [
        loc.text
        for loc in root.findall(".//s:loc", ns)
        if loc.text is not None
    ]
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_vaga_parsers.py::test_parse_sitemap_urls -v
```

Expected: PASS

- [ ] **Step 5: Write failing tests for category page parsing**

Add to `tests/test_vaga_parsers.py`:

```python
from book_scraper.spiders.vaga.parsers import parse_category_page


def test_parse_category_page():
    html = (FIXTURES / "vaga_category_page.html").read_text()
    products = parse_category_page(html)
    assert len(products) > 0
    first = products[0]
    assert "url" in first
    assert "title" in first
    assert "price" in first
    assert first["url"].startswith("https://vaga.lt/")
```

- [ ] **Step 6: Run test to verify it fails**

```bash
uv run pytest tests/test_vaga_parsers.py::test_parse_category_page -v
```

Expected: FAIL

- [ ] **Step 7: Implement parse_category_page**

Add to `book_scraper/spiders/vaga/parsers.py`:

```python
def parse_category_page(html: str) -> list[dict]:
    """Parse product cards from a vaga.lt category listing page.

    Returns list of dicts with keys: url, title, price, price_original, image_url.
    Prices are in Lithuanian format: '16,32€' → Decimal('16.32').
    """
    products = []
    segments = re.split(r'class="name">', html)[1:]
    for seg in segments:
        link_match = re.search(r'<a href="([^"]+)">([^<]+)', seg)
        if not link_match:
            continue
        url = link_match.group(1)
        title = link_match.group(2).strip()

        price = None
        price_match = re.search(r'class="price coupon"[^>]*>\s*([0-9,]+)€', seg)
        if price_match:
            price = price_match.group(1).replace(",", ".")

        price_original = None
        original_match = re.search(r'class="price-old"[^>]*>\s*([0-9,]+)€', seg)
        if original_match:
            price_original = original_match.group(1).replace(",", ".")

        image_url = None
        img_match = re.search(r'data-src="([^"]+)"', seg)
        if img_match:
            image_url = img_match.group(1)

        products.append({
            "url": url,
            "title": title,
            "price": price,
            "price_original": price_original,
            "image_url": image_url,
        })
    return products
```

- [ ] **Step 8: Run test to verify it passes**

```bash
uv run pytest tests/test_vaga_parsers.py::test_parse_category_page -v
```

Expected: PASS

- [ ] **Step 9: Write failing tests for product page parsing**

Add to `tests/test_vaga_parsers.py`:

```python
from book_scraper.spiders.vaga.parsers import parse_product_page


def test_parse_product_page():
    html = (FIXTURES / "vaga_product_page.html").read_text()
    data = parse_product_page(html)
    assert data["title"] is not None
    assert data["price"] is not None
    # ISBN may or may not be present depending on the fixture
    assert "isbn" in data
    assert "in_stock" in data
    assert "categories" in data
```

- [ ] **Step 10: Run test to verify it fails**

```bash
uv run pytest tests/test_vaga_parsers.py::test_parse_product_page -v
```

Expected: FAIL

- [ ] **Step 11: Implement parse_product_page**

Add to `book_scraper/spiders/vaga/parsers.py`:

```python
def parse_product_page(html: str) -> dict:
    """Parse a vaga.lt product page using JSON-LD and HTML property spans.

    Returns dict with keys: title, description, price, price_original,
    in_stock, isbn, sku, publisher, image_url, categories,
    year, pages, cover_type.
    """
    data: dict = {
        "title": None,
        "description": None,
        "price": None,
        "price_original": None,
        "in_stock": None,
        "isbn": None,
        "sku": None,
        "publisher": None,
        "image_url": None,
        "categories": [],
        "year": None,
        "pages": None,
        "cover_type": None,
    }

    # Parse JSON-LD blocks
    blocks = re.findall(
        r'<script type="application/ld\+json">\s*(.*?)\s*</script>',
        html,
        re.DOTALL,
    )
    for block in blocks:
        cleaned = re.sub(r"[\x00-\x1f]+", " ", block.strip())
        try:
            ld = json.loads(cleaned)
        except json.JSONDecodeError:
            continue

        # Product/Book data
        ld_type = ld.get("@type", "")
        if isinstance(ld_type, list):
            is_product = "Product" in ld_type or "Book" in ld_type
        else:
            is_product = ld_type in ("Product", "Book")

        if is_product:
            data["title"] = ld.get("name")
            data["description"] = ld.get("description")
            data["sku"] = ld.get("sku")
            offers = ld.get("offers", {})
            data["price"] = offers.get("price")
            data["in_stock"] = "InStock" in offers.get("availability", "")
            related = ld.get("isRelatedTo", {})
            data["isbn"] = related.get("isbn")
            brand = ld.get("brand", {})
            data["publisher"] = brand.get("name")
            images = ld.get("image", [])
            if images:
                data["image_url"] = images[0] if isinstance(images, list) else images

        # Breadcrumb → categories
        if ld.get("@type") == "BreadcrumbList":
            items = ld.get("itemListElement", [])
            data["categories"] = [
                item.get("name", "")
                for item in items
                if item.get("name")
            ]

    # Parse HTML property spans (note: class has typo "propery")
    props = re.findall(
        r'<span class="propery-title">(.*?)</span>\s*<span class="propery-des">(.*?)</span>',
        html,
    )
    prop_map = {k.strip(): v.strip() for k, v in props}
    if "ISBN" in prop_map:
        data["isbn"] = data["isbn"] or prop_map["ISBN"]
    if "Metai" in prop_map:
        try:
            data["year"] = int(prop_map["Metai"])
        except ValueError:
            pass
    if "Puslapiai" in prop_map:
        try:
            data["pages"] = int(prop_map["Puslapiai"])
        except ValueError:
            pass
    if "Viršelis" in prop_map:
        data["cover_type"] = prop_map["Viršelis"]
    if "Leidykla" in prop_map:
        data["publisher"] = data["publisher"] or prop_map["Leidykla"]

    return data
```

- [ ] **Step 12: Run all parser tests**

```bash
uv run pytest tests/test_vaga_parsers.py -v
```

Expected: all tests PASS.

- [ ] **Step 13: Commit**

```bash
git add -A
git commit -m "feat: add vaga.lt parsers (sitemap, category, product) with tests"
```

---

### Task 7: Vaga.lt discovery spider (Phase 1)

**Files:**
- Create: `book_scraper/spiders/vaga/discover.py`

- [ ] **Step 1: Create the discovery spider**

```python
# book_scraper/spiders/vaga/discover.py
import scrapy

from book_scraper.items import DiscoveredUrlItem
from book_scraper.spiders.vaga.parsers import parse_sitemap_urls


class VagaDiscoverSpider(scrapy.Spider):
    name = "vaga_discover"
    allowed_domains = ["vaga.lt"]

    def start_requests(self):
        yield scrapy.Request("https://vaga.lt/sitemap.xml")

    def parse(self, response):
        urls = parse_sitemap_urls(response.text)
        self.logger.info("Found %d URLs in sitemap", len(urls))
        for url in urls:
            yield DiscoveredUrlItem(url=url, shop_name="vaga")
```

- [ ] **Step 2: Verify spider is listed**

```bash
uv run scrapy list
```

Expected: `vaga_discover` appears in output.

- [ ] **Step 3: Test spider with limited output**

```bash
uv run scrapy crawl vaga_discover -o discovered_urls.json -s CLOSESPIDER_ITEMCOUNT=10
```

Expected: `discovered_urls.json` contains up to 10 URL items.

- [ ] **Step 4: Clean up and commit**

```bash
rm -f discovered_urls.json
git add -A
git commit -m "feat: add vaga_discover spider (Phase 1 - sitemap)"
```

---

### Task 8: Vaga.lt full scan spider (Phase 3)

**Files:**
- Create: `book_scraper/spiders/vaga/scan.py`

- [ ] **Step 1: Create the full scan spider**

```python
# book_scraper/spiders/vaga/scan.py
import scrapy

from book_scraper.items import ListingItem
from book_scraper.spiders.vaga.parsers import parse_product_page


class VagaScanSpider(scrapy.Spider):
    name = "vaga_scan"
    allowed_domains = ["vaga.lt"]

    def __init__(self, urls_file=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.urls_file = urls_file

    def start_requests(self):
        if self.urls_file:
            with open(self.urls_file) as f:
                for line in f:
                    url = line.strip()
                    if url:
                        yield scrapy.Request(url, callback=self.parse_product)
        else:
            # Default: paginate category pages to find all product URLs
            yield scrapy.Request(
                "https://vaga.lt/knygos?limit=100&page=1",
                callback=self.parse_category,
                meta={"page": 1},
            )

    def parse_category(self, response):
        links = response.css('div.name a::attr(href)').getall()
        if not links:
            return
        for link in links:
            yield response.follow(link, callback=self.parse_product)

        # Follow pagination
        page = response.meta["page"] + 1
        yield scrapy.Request(
            f"https://vaga.lt/knygos?limit=100&page={page}",
            callback=self.parse_category,
            meta={"page": page},
        )

    def parse_product(self, response):
        data = parse_product_page(response.text)

        # Skip non-book products
        if data["title"] is None:
            return

        yield ListingItem(
            url=response.url,
            shop_name="vaga",
            shop_title=data["title"],
            shop_author=data.get("author"),
            isbn=data.get("isbn"),
            publisher=data.get("publisher"),
            year=data.get("year"),
            pages=data.get("pages"),
            cover_type=data.get("cover_type"),
            description=data.get("description"),
            image_url=data.get("image_url"),
            price=data.get("price"),
            price_original=data.get("price_original"),
            in_stock=data.get("in_stock"),
            categories=data.get("categories", []),
        )
```

- [ ] **Step 2: Test spider with limited output**

```bash
uv run scrapy crawl vaga_scan -o scan_test.json -s CLOSESPIDER_ITEMCOUNT=5
```

Expected: `scan_test.json` contains up to 5 product items with title, price, ISBN, etc.

- [ ] **Step 3: Clean up and commit**

```bash
rm -f scan_test.json
git add -A
git commit -m "feat: add vaga_scan spider (Phase 3 - full product data)"
```

---

### Task 9: Vaga.lt price spider (Phase 4)

**Files:**
- Create: `book_scraper/spiders/vaga/prices.py`

- [ ] **Step 1: Create the price-only spider**

```python
# book_scraper/spiders/vaga/prices.py
import scrapy

from book_scraper.items import PriceItem
from book_scraper.spiders.vaga.parsers import parse_category_page


class VagaPricesSpider(scrapy.Spider):
    name = "vaga_prices"
    allowed_domains = ["vaga.lt"]

    custom_settings = {
        "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
        "DOWNLOAD_DELAY": 0.5,
    }

    def start_requests(self):
        yield scrapy.Request(
            "https://vaga.lt/knygos?limit=100&page=1",
            meta={"page": 1},
        )

    def parse(self, response):
        products = parse_category_page(response.text)
        if not products:
            return

        for product in products:
            if product["price"] is not None:
                yield PriceItem(
                    url=product["url"],
                    shop_name="vaga",
                    price=product["price"],
                    price_original=product["price_original"],
                    in_stock=True,  # listing pages don't show stock status
                )

        # Follow pagination
        page = response.meta["page"] + 1
        yield scrapy.Request(
            f"https://vaga.lt/knygos?limit=100&page={page}",
            callback=self.parse,
            meta={"page": page},
        )
```

- [ ] **Step 2: Test spider**

```bash
uv run scrapy crawl vaga_prices -o prices_test.json -s CLOSESPIDER_ITEMCOUNT=10
```

Expected: `prices_test.json` contains price items.

- [ ] **Step 3: Clean up and commit**

```bash
rm -f prices_test.json
git add -A
git commit -m "feat: add vaga_prices spider (Phase 4 - price re-scraping)"
```

---

### Task 10: PostgreSQL pipelines

**Files:**
- Modify: `book_scraper/pipelines.py`
- Modify: `book_scraper/settings.py`

- [ ] **Step 1: Implement ValidationPipeline and PostgresPipeline**

```python
# book_scraper/pipelines.py
from decimal import Decimal, InvalidOperation

from itemadapter import ItemAdapter
from scrapy.exceptions import DropItem
from sqlalchemy.orm import Session

from book_scraper.db.repo import insert_price, upsert_listing, upsert_shop
from book_scraper.db.session import get_session_factory
from book_scraper.items import DiscoveredUrlItem, ListingItem, PriceItem


class ValidationPipeline:
    def process_item(self, item, spider):
        adapter = ItemAdapter(item)

        if isinstance(item, (ListingItem, PriceItem)):
            price = adapter.get("price")
            if price is not None:
                try:
                    adapter["price"] = str(Decimal(str(price)))
                except (InvalidOperation, ValueError):
                    raise DropItem(f"Invalid price: {price}")

            price_original = adapter.get("price_original")
            if price_original is not None:
                try:
                    adapter["price_original"] = str(Decimal(str(price_original)))
                except (InvalidOperation, ValueError):
                    adapter["price_original"] = None

        if isinstance(item, ListingItem):
            if not adapter.get("shop_title"):
                raise DropItem("Missing shop_title")

        return item


class PostgresPipeline:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.session_factory = None
        self.session: Session | None = None
        self.shop_cache: dict[str, int] = {}

    @classmethod
    def from_crawler(cls, crawler):
        return cls(database_url=crawler.settings.get("DATABASE_URL"))

    def open_spider(self, spider):
        self.session_factory = get_session_factory(self.database_url)
        self.session = self.session_factory()

    def close_spider(self, spider):
        if self.session:
            self.session.commit()
            self.session.close()

    def _get_shop_id(self, shop_name: str) -> int:
        if shop_name not in self.shop_cache:
            shop = upsert_shop(
                self.session,
                name=shop_name,
                base_url=f"https://{shop_name}.lt",
            )
            self.shop_cache[shop_name] = shop.id
        return self.shop_cache[shop_name]

    def process_item(self, item, spider):
        if self.session is None:
            return item

        adapter = ItemAdapter(item)
        shop_name = adapter.get("shop_name")

        if isinstance(item, ListingItem):
            shop_id = self._get_shop_id(shop_name)
            listing = upsert_listing(
                self.session,
                shop_id=shop_id,
                url=adapter["url"],
                shop_title=adapter["shop_title"],
                shop_author=adapter.get("shop_author"),
                isbn_from_shop=adapter.get("isbn"),
                image_url=adapter.get("image_url"),
            )
            if adapter.get("price") is not None:
                insert_price(
                    self.session,
                    listing_id=listing.id,
                    price=Decimal(adapter["price"]),
                    price_original=(
                        Decimal(adapter["price_original"])
                        if adapter.get("price_original")
                        else None
                    ),
                    in_stock=adapter.get("in_stock", True),
                )

        elif isinstance(item, PriceItem):
            shop_id = self._get_shop_id(shop_name)
            listing = upsert_listing(
                self.session,
                shop_id=shop_id,
                url=adapter["url"],
                shop_title=adapter.get("url", ""),  # fallback, price spider may not have title
            )
            insert_price(
                self.session,
                listing_id=listing.id,
                price=Decimal(adapter["price"]),
                price_original=(
                    Decimal(adapter["price_original"])
                    if adapter.get("price_original")
                    else None
                ),
                in_stock=adapter.get("in_stock", True),
            )

        # Commit every 100 items for performance
        if hasattr(spider, "_item_count"):
            spider._item_count += 1
        else:
            spider._item_count = 1
        if spider._item_count % 100 == 0:
            self.session.commit()

        return item
```

- [ ] **Step 2: Enable pipelines in settings.py**

Add to `book_scraper/settings.py` (replace the commented-out section):

```python
ITEM_PIPELINES = {
    "book_scraper.pipelines.ValidationPipeline": 100,
    "book_scraper.pipelines.PostgresPipeline": 200,
}
```

- [ ] **Step 3: Test end-to-end with vaga_prices spider**

```bash
uv run scrapy crawl vaga_prices -s CLOSESPIDER_ITEMCOUNT=20
```

Expected: items stored in PostgreSQL `listings` and `prices` tables. Verify with:

```bash
psql book_scraper -c "SELECT COUNT(*) FROM listings; SELECT COUNT(*) FROM prices;"
```

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "feat: add PostgreSQL pipelines (validation + storage)"
```

---

### Task 11: Scrapy items validation tests

**Files:**
- Create: `tests/test_items.py`

- [ ] **Step 1: Write item validation tests**

```python
# tests/test_items.py
from decimal import Decimal

import pytest
from itemadapter import ItemAdapter
from scrapy.exceptions import DropItem

from book_scraper.items import ListingItem, PriceItem
from book_scraper.pipelines import ValidationPipeline


@pytest.fixture
def pipeline():
    return ValidationPipeline()


def test_valid_listing_item_passes(pipeline):
    item = ListingItem(
        url="https://vaga.lt/book",
        shop_name="vaga",
        shop_title="Test Book",
        price="9.99",
    )
    result = pipeline.process_item(item, spider=None)
    assert ItemAdapter(result)["price"] == "9.99"


def test_listing_item_without_title_dropped(pipeline):
    item = ListingItem(url="https://vaga.lt/book", shop_name="vaga")
    with pytest.raises(DropItem, match="Missing shop_title"):
        pipeline.process_item(item, spider=None)


def test_invalid_price_dropped(pipeline):
    item = PriceItem(
        url="https://vaga.lt/book",
        shop_name="vaga",
        price="not_a_number",
    )
    with pytest.raises(DropItem, match="Invalid price"):
        pipeline.process_item(item, spider=None)


def test_lithuanian_price_format(pipeline):
    item = PriceItem(
        url="https://vaga.lt/book",
        shop_name="vaga",
        price="16.32",
        price_original="24.39",
    )
    result = pipeline.process_item(item, spider=None)
    adapter = ItemAdapter(result)
    assert adapter["price"] == "16.32"
    assert adapter["price_original"] == "24.39"
```

- [ ] **Step 2: Run tests**

```bash
uv run pytest tests/test_items.py -v
```

Expected: all tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_items.py
git commit -m "test: add item validation pipeline tests"
```

---

### Task 12: Lint and type check

**Files:**
- Potentially fix any issues in all `book_scraper/` and `tests/` files

- [ ] **Step 1: Run Ruff linter**

```bash
uv run ruff check book_scraper/ tests/
```

Fix any issues reported.

- [ ] **Step 2: Run Ruff formatter**

```bash
uv run ruff format book_scraper/ tests/
```

- [ ] **Step 3: Run mypy**

```bash
uv run mypy book_scraper/
```

Fix type errors. Note: Scrapy items are dynamic dicts, so some `# type: ignore` may be needed.

- [ ] **Step 4: Run full test suite**

```bash
uv run pytest -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: fix lint and type issues"
```

---

## Summary

| Task | What it builds | Dependencies |
|------|---------------|-------------|
| 1 | Project reset: move prototypes, rewrite pyproject.toml | None |
| 2 | Scrapy skeleton: settings, items, pipelines stub | Task 1 |
| 3 | DB models + Alembic migration | Task 2 |
| 4 | DB repository (CRUD) + tests | Task 3 |
| 5 | vaga.lt HTML/XML test fixtures | Task 2 |
| 6 | vaga.lt parsers + tests | Task 5 |
| 7 | vaga_discover spider (Phase 1) | Task 6 |
| 8 | vaga_scan spider (Phase 3) | Task 6 |
| 9 | vaga_prices spider (Phase 4) | Task 6 |
| 10 | PostgreSQL pipelines | Tasks 4, 7-9 |
| 11 | Item validation tests | Task 10 |
| 12 | Lint + type check | All |
