"""Getting text out of files and web pages.

One module, because there were two: the chat layer read a page one way to
attach it to a message, and the index read it another way to embed it, each
with its own three-deep chain of bare `except:`. They wanted the same text.
The list of file types they accept was written out three times as well, and a
fourth time as a file-dialog filter.
"""

import logging

import requests
from llama_index.core import SimpleDirectoryReader
from llama_index.readers.web import (
    BeautifulSoupWebReader,
    MainContentExtractorReader,
    TrafilaturaWebReader,
)

from vollama.errors import DocumentError

log = logging.getLogger(__name__)

# What can be read as a document, for attaching and for indexing alike. The
# file dialogs build their filter from this, so a type added here appears
# everywhere it should.
DOCUMENT_EXTENSIONS = (
    ".txt",
    ".md",
    ".pdf",
    ".docx",
    ".pptx",
    ".ppt",
    ".pptm",
    ".hwp",
    ".csv",
    ".epub",
    ".mbox",
)

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")

# Readers in the order they are tried. The first extracts an article cleanly
# when the page is an article; the second copes with more layouts; the third
# will take anything with tags in it. A page that beats all three is a page we
# cannot read, and saying so is better than attaching an empty document.
PAGE_READERS = (
    MainContentExtractorReader,
    TrafilaturaWebReader,
    BeautifulSoupWebReader,
)

TIMEOUT = 30


def wildcard(label, extensions):
    """A wx file-dialog filter built from an extension list."""
    patterns = ";".join(f"*{extension}" for extension in extensions)
    return f"{label} ({patterns})|{patterns}"


def load(source):
    """Documents from a folder, or from a list of specific files."""
    if isinstance(source, (list, tuple)):
        reader = SimpleDirectoryReader(input_files=list(source))
    else:
        reader = SimpleDirectoryReader(
            source, recursive=True, required_exts=list(DOCUMENT_EXTENSIONS)
        )
    documents = reader.load_data()
    if not documents:
        raise DocumentError(f"Nothing readable was found in {source}.")
    return documents


def read_files(paths):
    """The text of these files, each fenced and labelled with its name.

    Fenced because it is about to be pasted into a message: the model has to be
    able to tell the document from the question, and where one file ends.
    """
    documents = load(list(paths))
    return "\n---\n".join(
        f"```{document.metadata.get('file_name', '')}\n{document.text}\n```"
        for document in documents
    )


def fetch_page(url):
    """The readable text of a web page.

    Each reader is tried in turn and its failure logged, rather than swallowed:
    when a page comes back empty it matters which of the three managed to fetch
    it and returned nothing.
    """
    for reader in PAGE_READERS:
        try:
            documents = reader().load_data([url])
        except Exception as e:
            # Third-party readers raise whatever their parser raises, and the
            # answer to any of it is the same: try the next one.
            log.info("%s could not read %s: %s", reader.__name__, url, e)
            continue
        if documents and documents[0].text.strip():
            return documents[0].text.strip()
        log.info("%s found no text at %s", reader.__name__, url)
    raise DocumentError(f"No readable text was found at {url}.")


def is_image_url(url):
    """Whether this address is a picture rather than a page.

    Decided by asking the server, since an image URL need not end in .png. A
    server that will not answer is taken at its word: not an image.
    """
    if url.lower().endswith(IMAGE_EXTENSIONS):
        return True
    try:
        response = requests.head(url, allow_redirects=True, timeout=5)
    except requests.RequestException as e:
        log.info("Could not check the type of %s: %s", url, e)
        return False
    return response.headers.get("Content-Type", "").startswith("image/")


def read_image(source):
    """The bytes of an image, from a local file or an address.

    Bytes rather than base64, because what type of picture it is has to be read
    off the first of them: an address need not say, and a file's extension can
    be wrong.
    """
    try:
        if source.startswith("http"):
            response = requests.get(source, timeout=TIMEOUT)
            response.raise_for_status()
            content = response.content
        else:
            with open(source, "rb") as file:
                content = file.read()
    except (OSError, requests.RequestException) as e:
        raise DocumentError(f"Could not read the image {source}: {e}") from e
    return content
