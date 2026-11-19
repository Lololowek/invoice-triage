"""PDF -> text. Text layer only: scanned PDFs are out of scope (no OCR).

The text is rebuilt from pdfplumber's words, line by line, with one rule that the candidate finders
rely on: words are joined by ONE space when the gap between them looks like a space in that font,
and by TWO spaces when it is wider (a table column, a tab stop).

Why not pdfplumber's default text: it joins table cells with single spaces, so a row
"2 | 150 000,00" comes out as "2 150 000,00" and the quantity merges into the price.
Why not its layout mode: it maps x positions onto a fixed character grid, so large fonts get double
spaces between ordinary words, and a total printed in 14pt splits into "362  000,00".

All candidate spans refer to the text this module returns.
"""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path
from typing import Any, BinaryIO

import pdfplumber
from pdfplumber.utils.exceptions import PdfminerException

PAGE_BREAK = "\n\f\n"
COLUMN_GAP_EM = 0.6  # gap wider than 0.6 x font size = column; a space is ~0.3 em
BLANK_LINE_EM = 1.0  # vertical gap wider than this x font size = paragraph break


class NoTextLayerError(ValueError):
    """The PDF has no extractable text (a scan). OCR is not supported."""


class NotAPdfError(ValueError):
    """The file cannot be parsed as a PDF."""


def _group_lines(words: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Group words into visual lines: a word joins a line if its vertical middle is inside it."""
    lines: list[dict[str, Any]] = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        middle = (w["top"] + w["bottom"]) / 2
        for line in reversed(lines[-3:]):
            if line["top"] - 1 <= middle <= line["bottom"] + 1:
                line["words"].append(w)
                line["top"] = min(line["top"], w["top"])
                line["bottom"] = max(line["bottom"], w["bottom"])
                break
        else:
            lines.append({"top": w["top"], "bottom": w["bottom"], "words": [w]})
    lines.sort(key=lambda line: line["top"])
    return [sorted(line["words"], key=lambda w: w["x0"]) for line in lines]


def _join_line(words: list[dict[str, Any]]) -> str:
    parts = [words[0]["text"]]
    for prev, word in pairwise(words):
        gap = word["x0"] - prev["x1"]
        size = max(prev["size"], word["size"])
        parts.append("  " if gap > COLUMN_GAP_EM * size else " ")
        parts.append(word["text"])
    return "".join(parts)


def page_text(page: Any) -> str:
    words = page.extract_words(x_tolerance=1.5, y_tolerance=2, extra_attrs=["size"])
    if not words:
        return ""
    out: list[str] = []
    previous_bottom: float | None = None
    for line in _group_lines(words):
        top = min(w["top"] for w in line)
        size = max(w["size"] for w in line)
        if previous_bottom is not None and top - previous_bottom > BLANK_LINE_EM * size:
            out.append("")
        out.append(_join_line(line).replace(" ", " ").replace(" ", " "))
        previous_bottom = max(w["bottom"] for w in line)
    return "\n".join(out)


def extract_text(source: str | Path | BinaryIO, name: str | None = None) -> str:
    """`source` is a path or a binary stream (an upload); `name` is used in error messages."""
    name = name or str(source)
    try:
        with pdfplumber.open(source) as pdf:
            pages = [page_text(page) for page in pdf.pages]
    except PdfminerException as e:
        raise NotAPdfError(f"{name}: not a readable PDF ({e})") from e
    text = PAGE_BREAK.join(p for p in pages if p)
    if not text.strip():
        raise NoTextLayerError(f"{name}: no text layer (scanned PDF?); OCR is not supported")
    return text
