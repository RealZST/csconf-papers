from __future__ import annotations

import time
from typing import Callable


class RateLimited(Exception):
    """重试耗尽后仍被 DBLP 限流。"""


class HttpError(Exception):
    """非 429 的失败响应。"""


class Fetcher:
    """带节流与退避的取数层。

    sleep 与 session 注入是为了让测试完全离线且不真的等待。
    """

    def __init__(
        self,
        session,
        sleep: Callable[[float], None] = time.sleep,
        throttle_seconds: float = 4.0,
        base_backoff: float = 4.0,
        max_retries: int = 5,
        timeout: float = 40.0,
    ):
        self.session = session
        self.sleep = sleep
        self.throttle_seconds = throttle_seconds
        self.base_backoff = base_backoff
        self.max_retries = max_retries
        self.timeout = timeout
        self._made_request = False

    def get(self, url: str) -> str:
        if self._made_request and self.throttle_seconds:
            self.sleep(self.throttle_seconds)
        self._made_request = True

        backoff = self.base_backoff
        for attempt in range(self.max_retries):
            response = self.session.get(url, timeout=self.timeout)
            if response.status_code == 200:
                return response.text
            if response.status_code != 429:
                raise HttpError("{} 返回 {}".format(url, response.status_code))
            if attempt < self.max_retries - 1:
                self.sleep(backoff)
                backoff *= 2

        raise RateLimited("{} 连续 {} 次被限流".format(url, self.max_retries))


def toc_url(toc_key: str) -> str:
    return "https://dblp.org/db/{}.xml".format(toc_key)


def index_url(index_key: str) -> str:
    return "https://dblp.org/db/{}/index.html".format(index_key)
