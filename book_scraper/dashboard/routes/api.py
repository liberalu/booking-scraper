# book_scraper/dashboard/routes/api.py
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from book_scraper.dashboard.deps import get_db

router = APIRouter()
