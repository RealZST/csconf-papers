import pytest

from csconf.http import Fetcher, RateLimited


class FakeResponse:
    """A response carries headers and bytes, not just decoded text — the decoder
    reads all three to work out the charset."""

    def __init__(self, status_code, text="", content_type="text/html; charset=utf-8"):
        self.status_code = status_code
        self.text = text
        self.headers = {"content-type": content_type}
        self.content = text.encode("utf-8")


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

    # No wait before the first request, one throttle interval before the second
    assert sleeps == [4]


def test_retries_with_exponential_backoff_on_429():
    session = FakeSession([FakeResponse(429), FakeResponse(429), FakeResponse(200, "ok")])
    sleeps = []
    fetcher = Fetcher(session=session, sleep=sleeps.append, throttle_seconds=4, base_backoff=2)

    assert fetcher.get("https://example.org/x") == "ok"
    # One get: no throttle on the first request, a doubling backoff per 429
    assert sleeps == [2, 4]


def test_raises_after_max_retries():
    session = FakeSession([FakeResponse(429)] * 6)
    fetcher = Fetcher(
        session=session, sleep=lambda _: None, throttle_seconds=0, base_backoff=1, max_retries=5
    )

    with pytest.raises(RateLimited):
        fetcher.get("https://example.org/x")


def test_retries_on_503_not_just_429():
    """In the first full sync, six of eight failures were 503 rather than 429:
    that is how DBLP answers when overloaded. Retrying only 429 would fail most
    of a run whenever the server wobbles."""
    session = FakeSession([FakeResponse(503), FakeResponse(503), FakeResponse(200, "ok")])
    sleeps = []
    fetcher = Fetcher(session=session, sleep=sleeps.append, throttle_seconds=0, base_backoff=2)

    assert fetcher.get("https://example.org/x") == "ok"
    assert sleeps == [2, 4]


def test_404_raises_not_found_without_retrying():
    """A missing TOC is a stable state: retrying is pointless, and it has to be
    distinguishable from rate limiting — an unindexed edition (OSDI/ATC 2026)
    is exactly this 404."""
    from csconf.http import NotFound

    session = FakeSession([FakeResponse(404)])
    sleeps = []
    fetcher = Fetcher(session=session, sleep=sleeps.append, throttle_seconds=0)

    with pytest.raises(NotFound):
        fetcher.get("https://dblp.org/db/conf/osdi/osdi2026.xml")
    assert sleeps == [], "a 404 must not trigger backoff"


def test_non_retryable_status_carries_code():
    from csconf.http import HttpError

    session = FakeSession([FakeResponse(500)])
    fetcher = Fetcher(session=session, sleep=lambda _: None, throttle_seconds=0)

    with pytest.raises(HttpError) as excinfo:
        fetcher.get("https://example.org/x")
    assert excinfo.value.status_code == 500


def test_read_timeout_is_retried_then_succeeds():
    """Under pressure DBLP hangs the connection, which shows up as a read
    timeout rather than a status code. Without a retry, one timeout kills the
    run halfway and wastes every venue that already succeeded."""
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


def test_head_reports_whether_a_pdf_is_actually_served():
    """A derived PDF URL has to be checked once. A 200 that returns HTML means we
    landed on an error page — that is exactly how usenix.org answers a missing
    file, so looking at the status code alone would count it as a hit."""
    class HeadSession:
        def __init__(self, status, content_type):
            self.status, self.content_type = status, content_type
            self.calls = []

        def head(self, url, timeout=None, allow_redirects=None):
            self.calls.append(url)
            return type(
                "R", (), {"status_code": self.status, "headers": {"content-type": self.content_type}}
            )()

    ok = Fetcher(session=HeadSession(200, "application/pdf"), sleep=lambda _: None, throttle_seconds=0)
    assert ok.head_is_pdf("https://www.usenix.org/system/files/osdi26-yu-shan.pdf") is True

    html = Fetcher(session=HeadSession(200, "text/html; charset=utf-8"), sleep=lambda _: None, throttle_seconds=0)
    assert html.head_is_pdf("https://www.usenix.org/system/files/nope.pdf") is False

    missing = Fetcher(session=HeadSession(404, ""), sleep=lambda _: None, throttle_seconds=0)
    assert missing.head_is_pdf("https://www.usenix.org/system/files/nope.pdf") is False


def test_head_failures_are_not_fatal():
    """Filling in PDFs is a bonus. A blip in the network must not fail the run."""
    import requests

    class Broken:
        def head(self, url, timeout=None, allow_redirects=None):
            raise requests.ConnectionError("boom")

    fetcher = Fetcher(session=Broken(), sleep=lambda _: None, throttle_seconds=0)
    assert fetcher.head_is_pdf("https://example.org/x.pdf") is False


def test_post_json_returns_the_body():
    """The Semantic Scholar batch endpoint is a POST, and it is the only reason
    977 papers cost two requests instead of 977."""
    class PostSession:
        def __init__(self):
            self.calls = []

        def post(self, url, json=None, timeout=None):
            self.calls.append((url, json))
            return FakeResponse(200, '[{"title": "x"}]')

    session = PostSession()
    fetcher = Fetcher(session=session, sleep=lambda _: None, throttle_seconds=0)

    assert fetcher.post_json("https://api.example/batch", {"ids": ["DOI:1"]}) == '[{"title": "x"}]'
    assert session.calls[0][1] == {"ids": ["DOI:1"]}


def test_post_json_retries_rate_limiting_like_get():
    class Flaky:
        def __init__(self):
            self.n = 0

        def post(self, url, json=None, timeout=None):
            self.n += 1
            return FakeResponse(200, "ok") if self.n > 1 else FakeResponse(429)

    sleeps = []
    fetcher = Fetcher(session=Flaky(), sleep=sleeps.append, throttle_seconds=0, base_backoff=2)

    assert fetcher.post_json("https://api.example/batch", {"ids": []}) == "ok"
    assert sleeps == [2]


def test_utf8_body_is_decoded_when_the_server_omits_a_charset():
    """sigops.org answers "content-type: text/html" with no charset, and requests
    then falls back to ISO-8859-1 per RFC 2616. The page is UTF-8 and says so in
    a meta tag, so that fallback turned "Wagenländer" into "WagenlÃ¤nder" in a
    published author list."""
    class NoCharset:
        def get(self, url, timeout=None):
            body = "Marcel Wagenländer".encode("utf-8")
            return type(
                "R", (), {
                    "status_code": 200,
                    "headers": {"content-type": "text/html"},
                    "content": body,
                    # What requests would hand us: UTF-8 bytes read as latin-1.
                    "text": body.decode("latin-1"),
                },
            )()

    fetcher = Fetcher(session=NoCharset(), sleep=lambda _: None, throttle_seconds=0)

    assert fetcher.get("https://www.sigops.org/x") == "Marcel Wagenländer"


def test_declared_charset_is_respected():
    """When the server does declare one, believe it rather than guessing."""
    class Declared:
        def get(self, url, timeout=None):
            return type(
                "R", (), {
                    "status_code": 200,
                    "headers": {"content-type": "text/html; charset=iso-8859-1"},
                    "content": "café".encode("latin-1"),
                    "text": "café",
                },
            )()

    fetcher = Fetcher(session=Declared(), sleep=lambda _: None, throttle_seconds=0)

    assert fetcher.get("https://example.org/x") == "café"
