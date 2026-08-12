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


def test_retries_on_503_not_just_429():
    """实测首次全量同步：DBLP 过载时返回 503 而非 429，8 个失败里 6 个是 503。
    只重试 429 会让整轮同步在服务端抖动时大面积失败。"""
    session = FakeSession([FakeResponse(503), FakeResponse(503), FakeResponse(200, "ok")])
    sleeps = []
    fetcher = Fetcher(session=session, sleep=sleeps.append, throttle_seconds=0, base_backoff=2)

    assert fetcher.get("https://example.org/x") == "ok"
    assert sleeps == [2, 4]


def test_404_raises_not_found_without_retrying():
    """TOC 不存在是稳定状态，重试没有意义，而且要能与限流区分开——
    尚未编目的会议（OSDI/ATC 2026）就是 404。"""
    from csconf.http import NotFound

    session = FakeSession([FakeResponse(404)])
    sleeps = []
    fetcher = Fetcher(session=session, sleep=sleeps.append, throttle_seconds=0)

    with pytest.raises(NotFound):
        fetcher.get("https://dblp.org/db/conf/osdi/osdi2026.xml")
    assert sleeps == [], "404 不应触发退避"


def test_non_retryable_status_carries_code():
    from csconf.http import HttpError

    session = FakeSession([FakeResponse(500)])
    fetcher = Fetcher(session=session, sleep=lambda _: None, throttle_seconds=0)

    with pytest.raises(HttpError) as excinfo:
        fetcher.get("https://example.org/x")
    assert excinfo.value.status_code == 500


def test_read_timeout_is_retried_then_succeeds():
    """DBLP 压力下会把连接挂住，表现为读超时而非状态码。不重试的话
    一次超时就让整轮同步崩在半路，已成功的会议全部白跑。"""
    import requests

    class TimeoutThenOk:
        def __init__(self):
            self.calls = 0

        def get(self, url, timeout=None):
            self.calls += 1
            if self.calls == 1:
                raise requests.Timeout("read timed out")
            return FakeResponse(200, "ok")

    sleeps = []
    fetcher = Fetcher(
        session=TimeoutThenOk(), sleep=sleeps.append, throttle_seconds=0, base_backoff=2
    )

    assert fetcher.get("https://dblp.org/db/conf/sosp/sosp2025.xml") == "ok"
    assert sleeps == [2]


def test_persistent_timeout_raises_rate_limited():
    import requests

    class AlwaysTimeout:
        def get(self, url, timeout=None):
            raise requests.Timeout("read timed out")

    fetcher = Fetcher(
        session=AlwaysTimeout(), sleep=lambda _: None, throttle_seconds=0, max_retries=3
    )

    with pytest.raises(RateLimited):
        fetcher.get("https://example.org/x")
