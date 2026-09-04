"""The library of saved system prompts.

Stored as `prompts.csv` next to the settings, in the two-column shape the
Awesome ChatGPT Prompts collection publishes, so the shared list can be merged
into a personal one without translating between two formats.

It lives here rather than in the editor that shows it because it is user data
with rules of its own — names are unique, the list is kept sorted, a merge
prefers the newer text — and none of that is a fact about a wx panel.
"""

import csv
import logging
from dataclasses import dataclass

import requests

from vollama.config.store import config_dir
from vollama.errors import VOLlamaError

log = logging.getLogger(__name__)

# The published collection, and how long we are willing to wait for it.
SHARED_URL = "https://github.com/f/awesome-chatgpt-prompts/raw/main/prompts.csv"
TIMEOUT = 30

# The column names in the file, which are the ones the shared collection uses.
NAME_COLUMN = "act"
TEXT_COLUMN = "prompt"


@dataclass(frozen=True)
class Prompt:
    name: str
    text: str


class PromptLibrary:
    """Saved prompts, kept sorted by name and unique by name."""

    def __init__(self, path=None):
        self.path = path or config_dir() / "prompts.csv"
        self.prompts = self._read()

    def _read(self):
        try:
            with open(self.path, encoding="utf-8", newline="") as file:
                rows = list(csv.DictReader(file))
        except FileNotFoundError:
            return []
        except (OSError, csv.Error) as e:
            log.error("Could not read %s: %s", self.path, e)
            return []
        return _sorted(
            Prompt(row.get(NAME_COLUMN) or "", row.get(TEXT_COLUMN) or "")
            for row in rows
            if row.get(NAME_COLUMN)
        )

    def names(self):
        return [prompt.name for prompt in self.prompts]

    def find(self, text):
        """The index of the prompt with this text, or None.

        Used to show which saved prompt a preset is currently using.
        """
        for index, prompt in enumerate(self.prompts):
            if prompt.text == text:
                return index
        return None

    def put(self, name, text):
        """Add a prompt, or replace the one with that name. Returns its index."""
        name = name.strip()
        if not name:
            raise VOLlamaError("A saved prompt needs a name.")
        kept = [prompt for prompt in self.prompts if prompt.name != name]
        self.prompts = _sorted(kept + [Prompt(name, text)])
        self.save()
        return self.names().index(name)

    def remove(self, index):
        """Delete the prompt at this position."""
        if 0 <= index < len(self.prompts):
            del self.prompts[index]
            self.save()

    def merge(self, incoming):
        """Add prompts from the shared collection, its text winning on a clash."""
        by_name = {prompt.name: prompt for prompt in self.prompts}
        for prompt in incoming:
            by_name[prompt.name] = prompt
        self.prompts = _sorted(by_name.values())
        self.save()

    def save(self):
        try:
            with open(self.path, "w", encoding="utf-8", newline="") as file:
                writer = csv.writer(file)
                writer.writerow([NAME_COLUMN, TEXT_COLUMN])
                writer.writerows([[p.name, p.text] for p in self.prompts])
        except OSError as e:
            raise VOLlamaError(f"Could not save the prompt library: {e}") from e


def _sorted(prompts):
    return sorted(prompts, key=lambda prompt: prompt.name.casefold())


def fetch_shared():
    """Download the published prompt collection."""
    try:
        response = requests.get(SHARED_URL, timeout=TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as e:
        raise VOLlamaError(f"Could not download the prompts: {e}") from e
    rows = csv.DictReader(response.text.splitlines())
    return [
        Prompt(row.get(NAME_COLUMN) or "", row.get(TEXT_COLUMN) or "")
        for row in rows
        if row.get(NAME_COLUMN)
    ]
