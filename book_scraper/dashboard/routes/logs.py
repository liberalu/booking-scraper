import asyncio
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from book_scraper.dashboard.deps import templates

router = APIRouter()

LOG_FILE = Path("scrapy_errors.log")


@router.get("/logs")
def logs_page(request: Request):
    lines: list[str] = []
    if LOG_FILE.exists():
        all_lines = LOG_FILE.read_text().splitlines()
        lines = all_lines[-100:]
    return templates.TemplateResponse(
        request,
        "logs.html",
        {
            "active_page": "logs",
            "lines": lines,
        },
    )


async def _stream_log():
    if not LOG_FILE.exists():
        yield "data: Log file not found\n\n"
        return
    with open(LOG_FILE) as f:
        f.seek(0, 2)  # seek to end
        while True:
            line = f.readline()
            if line:
                yield f"data: {line.rstrip()}\n\n"
            else:
                await asyncio.sleep(1)


@router.get("/api/logs/stream")
def logs_stream():
    return StreamingResponse(_stream_log(), media_type="text/event-stream")
