# ==================================================================================================================================
# Copyright (c) 2026 Stephen Copplestone and the piclas-db contributors (see CONTRIBUTORS.md)
#
# This file is part of piclas-db (github.com/piclas-framework/piclas-db). piclas-db is free software: you can redistribute it and/or
# modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3
# of the License, or (at your option) any later version.
#
# piclas-db is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty
# of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License v3.0 for more details.
#
# You should have received a copy of the GNU General Public License along with piclas-db. If not, see <https://www.gnu.org/licenses/>.
# ==================================================================================================================================
"""The same paper in another file: a journal cover page added or removed, a watermark with the download date, a re-download. Found
by the DOI (reliable) or, for papers without DOI, by the text of the first pages (shingles of words, compared with tolerance)."""

# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import pathlib
import re
from dataclasses import dataclass
from typing import Optional

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.sources.doi import pdf_text
from piclas_db.store import Store, StoreEntry
# ==================================================================================================================================

PAGES = 8  # pages compared (enough to see past a cover page)
SHINGLE = 5  # words per shingle
CONTAINMENT = 0.7  # share of the smaller shingle set found in the other: same paper
MINIMUM = 200  # shingles needed for a text comparison (less: a scan or a nearly empty text layer)


@dataclass
class Match:
    entry: StoreEntry
    key: str
    reason: str


def shingles(text: str) -> set[str]:
    words = re.findall(r'[a-z0-9]+', text.lower())
    return {' '.join(words[i : i + SHINGLE]) for i in range(max(len(words) - SHINGLE + 1, 0))}


def containment(a: set[str], b: set[str]) -> float:
    """Share of the smaller set that is in the larger one (an extra cover page or watermark changes little)"""
    if not a or not b:
        return 0.0
    small, large = (a, b) if len(a) <= len(b) else (b, a)
    return len(small & large) / len(small)


def pages(path: pathlib.Path) -> int:
    """Number of pages (page objects in the file; 0 if unknown)"""
    return len(re.findall(rb'/Type\s*/Page(?![s\w])', path.read_bytes()))


class SamePaper:
    """Finds a stored paper that is the same as a new file; the stored papers' texts are read once per run"""

    def __init__(self, store: Store) -> None:
        self.papers = [entry for entry in store.entries() if entry.meta.get('provider') == 'literature' and entry.meta.get('kind') == 'paper']
        self._texts: dict[str, set[str]] = {}

    def text(self, entry: StoreEntry) -> set[str]:
        checksum = str(entry.meta.get('sha256'))
        if checksum not in self._texts:
            self._texts[checksum] = shingles(pdf_text(entry.path, pages=PAGES))
        return self._texts[checksum]

    def find(self, path: pathlib.Path, doi: Optional[str]) -> Optional[Match]:
        if doi:
            for entry in self.papers:
                if str(entry.meta.get('doi') or '').lower() == doi.lower():
                    return Match(entry, str(entry.meta.get('dataset')), f'DOI {doi}')
        new = shingles(pdf_text(path, pages=PAGES))
        if len(new) < MINIMUM:
            return None
        best: Optional[tuple[float, StoreEntry]] = None
        for entry in self.papers:
            stored = self.text(entry)
            if len(stored) < MINIMUM:
                continue
            share = containment(new, stored)
            if share >= CONTAINMENT and (best is None or share > best[0]):
                best = (share, entry)
        if best is None:
            return None
        return Match(best[1], str(best[1].meta.get('dataset')), f'{best[0]:.0%} of the text of the first {PAGES} pages')
