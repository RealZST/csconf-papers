from __future__ import annotations

import time
from typing import Callable

import requests


class RateLimited(Exception):
    """The server is still refusing after the retries are spent."""


class HttpError(Exception):
    """A failure response that is not worth retrying."""

    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


class NotFound(HttpError):
    """The TOC does not exist. For an unindexed edition that is normal, not a fault."""


# Under load DBLP answers with 503, not only 429 — six of the eight failures in
# the first full sync were 503. Both are transient server-side refusals and both
# deserve a backoff and a retry.
RETRY_STATUSES = (429, 503)

# Under pressure DBLP also just hangs the connection, which surfaces as a read
# timeout rather than any status code. Those transport failures are transient
# too: without a retry a single timeout kills the run halfway through and throws
# away every venue that already succeeded.
TRANSIENT_EXCEPTIONS = (requests.Timeout, requests.ConnectionError)


class Fetcher:
    """Fetching with throttling and backoff.

    sleep and session are injected so the tests stay offline and never wait.
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

    def head_is_pdf(self, url: str) -> bool:
        """Report whether the URL actually serves a PDF.

        A derived URL is a guess, so it has to be checked before it goes into a
        public listing. Checking the status code alone is not enough: usenix.org
        answers a missing file with an HTML error page, which would otherwise
        count as a hit. Any failure here means "no PDF" rather than an error —
        a missing PDF link must never break the run.
        """
        if self._made_request and self.throttle_seconds:
            self.sleep(self.throttle_seconds)
        self._made_request = True

        try:
            response = self.session.head(
                url, timeout=self.timeout, allow_redirects=True
            )
        except Exception:
            return False

        if response.status_code != 200:
            return False
        return "pdf" in response.headers.get("content-type", "").lower()

    def get(self, url: str) -> str:
        return self._request(url, lambda: self.session.get(url, timeout=self.timeout))

    def post_json(self, url: str, payload) -> str:
        """POST a JSON body under the same throttling and backoff as get().

        The Semantic Scholar batch endpoint is a POST, and it is the only reason
        977 papers cost two requests instead of 977.
        """
        return self._request(
            url, lambda: self.session.post(url, json=payload, timeout=self.timeout)
        )

    def _request(self, url: str, send) -> str:
        if self._made_request and self.throttle_seconds:
            self.sleep(self.throttle_seconds)
        self._made_request = True

        backoff = self.base_backoff
        for attempt in range(self.max_retries):
            try:
                response = send()
            except TRANSIENT_EXCEPTIONS as exc:
                if attempt < self.max_retries - 1:
                    self.sleep(backoff)
                    backoff *= 2
                    continue
                raise RateLimited("{} kept timing out or failing to connect".format(url)) from exc

            if response.status_code == 200:
                return response.text
            if response.status_code == 404:
                raise NotFound("{} does not exist".format(url), 404)
            if response.status_code not in RETRY_STATUSES:
                raise HttpError(
                    "{} returned {}".format(url, response.status_code), response.status_code
                )
            if attempt < self.max_retries - 1:
                self.sleep(backoff)
                backoff *= 2

        raise RateLimited(
            "{} was refused {} times in a row (429/503)".format(url, self.max_retries)
        )


def toc_url(toc_key: str) -> str:
    return "https://dblp.org/db/{}.xml".format(toc_key)


def index_url(index_key: str) -> str:
    return "https://dblp.org/db/{}/index.html".format(index_key)
