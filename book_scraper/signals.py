"""Custom Scrapy signals defined by this project.

Scrapy signals are typically module-level sentinel objects so receivers
can connect via ``crawler.signals.connect(...)`` without name clashes.
See https://docs.scrapy.org/en/latest/topics/signals.html.
"""

# Fired by ScanSpider once `_run_id` has been assigned (which happens
# inside `start()`, *after* the standard `spider_opened` signal fires).
# Receivers (e.g. HeartbeatExtension) need to know the run_id before
# they can do useful work, so they connect to this signal instead of
# `spider_opened`.
#
# Emit:
#     self.crawler.signals.send_catch_log(
#         signal=run_started, sender=self, run_id=self._run_id,
#     )
#
# Receive:
#     def on_run_started(self, run_id: int, sender=None, **kwargs) -> None:
#         ...
run_started = object()
