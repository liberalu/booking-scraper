from collections.abc import Generator  # pragma: no cover
from typing import Any  # pragma: no cover

from scrapy import signals  # pragma: no cover


class BookScraperSpiderMiddleware:  # pragma: no cover
    @classmethod
    def from_crawler(cls, crawler: Any) -> "BookScraperSpiderMiddleware":
        s = cls()
        crawler.signals.connect(s.spider_opened, signal=signals.spider_opened)
        return s

    def process_spider_input(self, response: Any, spider: Any) -> None:
        return None

    def process_spider_output(
        self, response: Any, result: Any, spider: Any
    ) -> Generator[Any, None, None]:
        yield from result

    def process_spider_exception(
        self, response: Any, exception: Any, spider: Any
    ) -> None:
        pass

    def spider_opened(self, spider: Any) -> None:
        spider.logger.info(f"Spider opened: {spider.name}")
