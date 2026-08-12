import pytest

from csconf.http import Fetcher, RateLimited


class FakeResponse:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, timeout=None):
        self.calls.append(url)
        return self.responses.pop(0)


def test_returns_body_on_success():
    session = FakeSession([FakeResponse(200, "<bht/>")])
    sleeps = []
    fetcher = Fetcher(session=session, sleep=sleeps.append, throttle_seconds=4)

    assert fetcher.get("https://dblp.org/db/conf/sosp/sosp2025.xml") == "<bht/>"


def test_throttles_between_requests():
    session = FakeSession([FakeResponse(200, "a"), FakeResponse(200, "b")])
    sleeps = []
    fetcher = Fetcher(session=session, sleep=sleeps.append, throttle_seconds=4)

    fetcher.get("https://example.org/1")
    fetcher.get("https://example.org/2")

    # 第一次请求前不等待，第二次前等待一个节流间隔
    assert sleeps == [4]


def test_retries_with_exponential_backoff_on_429():
    session = FakeSession([FakeResponse(429), FakeResponse(429), FakeResponse(200, "ok")])
    sleeps = []
    fetcher = Fetcher(session=session, sleep=sleeps.append, throttle_seconds=4, base_backoff=2)

    assert fetcher.get("https://example.org/x") == "ok"
    # 单次 get：首次请求不节流，两次 429 各退避一轮，退避翻倍
    assert sleeps == [2, 4]


def test_raises_after_max_retries():
    session = FakeSession([FakeResponse(429)] * 6)
    fetcher = Fetcher(
        session=session, sleep=lambda _: None, throttle_seconds=0, base_backoff=1, max_retries=5
    )

    with pytest.raises(RateLimited):
        fetcher.get("https://example.org/x")
