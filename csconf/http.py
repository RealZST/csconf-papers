from __future__ import annotations

import time
from typing import Callable

import requests


class RateLimited(Exception):
    """重试耗尽后 DBLP 仍在拒绝服务。"""


class HttpError(Exception):
    """不可重试的失败响应。"""

    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


class NotFound(HttpError):
    """TOC 不存在。对尚未编目的会议来说这是正常状态，不是故障。"""


# DBLP 在过载或限流时会返回 503 而不只是 429——实测首次全量同步时
# 8 个失败里 6 个是 503。两者都是暂时性的服务端拒绝，都该退避重试。
RETRY_STATUSES = (429, 503)

# 压力之下 DBLP 还会直接把连接挂住，表现为读超时而非任何状态码。
# 这类传输层故障同样是暂时的：不重试的话，一次超时就会让整轮同步崩在半路，
# 已经成功的会议全部白跑。
TRANSIENT_EXCEPTIONS = (requests.Timeout, requests.ConnectionError)


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
            try:
                response = self.session.get(url, timeout=self.timeout)
            except TRANSIENT_EXCEPTIONS as exc:
                if attempt < self.max_retries - 1:
                    self.sleep(backoff)
                    backoff *= 2
                    continue
                raise RateLimited("{} 连续超时/连接失败".format(url)) from exc

            if response.status_code == 200:
                return response.text
            if response.status_code == 404:
                raise NotFound("{} 不存在".format(url), 404)
            if response.status_code not in RETRY_STATUSES:
                raise HttpError(
                    "{} 返回 {}".format(url, response.status_code), response.status_code
                )
            if attempt < self.max_retries - 1:
                self.sleep(backoff)
                backoff *= 2

        raise RateLimited(
            "{} 连续 {} 次被拒绝（429/503）".format(url, self.max_retries)
        )


def toc_url(toc_key: str) -> str:
    return "https://dblp.org/db/{}.xml".format(toc_key)


def index_url(index_key: str) -> str:
    return "https://dblp.org/db/{}/index.html".format(index_key)
