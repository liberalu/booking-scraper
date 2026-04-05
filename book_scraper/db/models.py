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

    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), primary_key=True)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id"), primary_key=True
    )


class Shop(Base):
    __tablename__ = "shops"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    base_url: Mapped[str] = mapped_column(String, nullable=False)

    listings: Mapped[list["Listing"]] = relationship(back_populates="shop")


match_status_enum = Enum(
    "unmatched", "matched", "uncertain", name="match_status", create_type=True
)
match_method_enum = Enum(
    "isbn", "fuzzy", "manual", name="match_method", create_type=True
)


class Listing(Base):
    __tablename__ = "listings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    book_id: Mapped[int | None] = mapped_column(ForeignKey("books.id"), nullable=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    shop_title: Mapped[str] = mapped_column(Text, nullable=False)
    shop_author: Mapped[str | None] = mapped_column(Text, nullable=True)
    isbn_from_shop: Mapped[str | None] = mapped_column(String, nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    match_status: Mapped[str] = mapped_column(
        match_status_enum, nullable=False, default="unmatched"
    )
    match_method: Mapped[str | None] = mapped_column(match_method_enum, nullable=True)
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
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id"), nullable=False)
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
