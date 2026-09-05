"""Reading a web page, which is three extractors over one download.

No test here reaches the network: `_download` is the only function that does,
and the three extractors are pure functions over a string of HTML, which is
the reason for the split.
"""

import pytest

from vollama.errors import DocumentError
from vollama.rag import documents

ARTICLE = """
<html><head><title>A title</title></head>
<body><article><h1>A title</h1>
<p>The sentence the page is for.</p></article></body></html>
"""


@pytest.mark.parametrize("reader", documents.PAGE_READERS)
def test_every_extractor_finds_the_text_of_an_article(reader):
    assert "The sentence the page is for." in reader(ARTICLE)


def test_the_first_extractor_that_finds_text_is_the_answer(monkeypatch):
    monkeypatch.setattr(documents, "_download", lambda url: ARTICLE)
    monkeypatch.setattr(
        documents, "PAGE_READERS", (lambda html: "  first  ", lambda html: "second")
    )
    assert documents.fetch_page("http://example.com") == "first"


def test_an_extractor_that_finds_nothing_hands_on_to_the_next(monkeypatch):
    """Empty, and raising, both mean the same thing: try the next one.

    A page one parser cannot make sense of is exactly why there are three, so
    neither may end the attempt.
    """

    def empty(html):
        return ""

    def broken(html):
        raise ValueError("no")

    monkeypatch.setattr(documents, "_download", lambda url: ARTICLE)
    monkeypatch.setattr(
        documents, "PAGE_READERS", (empty, broken, lambda html: "third")
    )
    assert documents.fetch_page("http://example.com") == "third"


def test_a_page_none_of_them_can_read_is_reported(monkeypatch):
    monkeypatch.setattr(documents, "_download", lambda url: ARTICLE)
    monkeypatch.setattr(documents, "PAGE_READERS", (lambda html: None,))
    with pytest.raises(DocumentError, match="No readable text"):
        documents.fetch_page("http://example.com")


class Response:
    """Enough of a `requests` response for `_download` to read."""

    def __init__(self, content, content_type, apparent_encoding="utf-8"):
        self.content = content
        self.headers = {"Content-Type": content_type}
        self.encoding = "ISO-8859-1"
        self.apparent_encoding = apparent_encoding

    def raise_for_status(self):
        pass

    @property
    def text(self):
        return self.content.decode(self.encoding)


def test_a_page_that_declares_no_charset_is_decoded_by_its_bytes(monkeypatch):
    """`requests` would otherwise call it ISO-8859-1 and mangle it.

    The readers this replaced each downloaded the page themselves, and this is
    the one thing doing it here has to get right: a Korean page served as
    text/html with no charset came back as mojibake.
    """
    page = "<p>한국어</p>".encode()
    monkeypatch.setattr(
        documents.requests, "get", lambda *a, **k: Response(page, "text/html")
    )
    assert documents._download("http://example.com") == "<p>한국어</p>"


def test_a_declared_charset_is_left_alone(monkeypatch):
    """The header is the page's own answer, and beats a guess at the bytes."""
    response = Response("<p>x</p>".encode("cp1252"), "text/html; charset=cp1252")
    response.encoding = "cp1252"
    monkeypatch.setattr(documents.requests, "get", lambda *a, **k: response)
    assert documents._download("http://example.com") == "<p>x</p>"


def test_a_page_that_cannot_be_fetched_is_reported_as_such(monkeypatch):
    def refuse(*a, **k):
        raise documents.requests.RequestException("no route to host")

    monkeypatch.setattr(documents.requests, "get", refuse)
    with pytest.raises(DocumentError, match="Could not read"):
        documents._download("http://example.com")
