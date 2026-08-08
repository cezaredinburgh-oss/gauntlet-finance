"""Auto-detect statement format from headers and light content sniffing."""

from __future__ import annotations

import csv
import io
from typing import Iterable

from backend.schema.models import ParserKey

# Zip/xlsx local file header
_XLSX_MAGIC = b"PK"

# Header fingerprints (normalized lowercase, stripped BOM)
_RAIFFEISEN_MARKERS = {
    "transaction date",
    "booking date",
    "booked amount",
    "transaction id",
}
_REVOLUT_EXPENSES_MARKERS = {
    "type",
    "product",
    "started date",
    "completed date",
    "description",
    "amount",
    "fee",
    "currency",
    "state",
    "balance",
}
_REVOLUT_CRYPTO_MARKERS = {
    "symbol",
    "type",
    "quantity",
    "price",
    "value",
    "fees",
    "date",
}
_REVOLUT_STOCKS_MARKERS = {
    "date",
    "ticker",
    "type",
    "quantity",
    "price per share",
    "total amount",
    "currency",
    "fx rate",
}
_ETORO_MARKERS = {
    "date",
    "platform",
    "eventtype",
    "ticker",
    "class",
    "side",
    "units",
    "pricenative",
    "currency",
    "valuenative",
    "feesnative",
    "comments",
}

_PARSER_TO_INSTITUTION: dict[str, str] = {
    ParserKey.RAIFFEISEN_CZ.value: "Raiffeisen",
    ParserKey.REVOLUT_EXPENSES.value: "Revolut",
    ParserKey.REVOLUT_CRYPTO.value: "Revolut",
    ParserKey.REVOLUT_STOCKS.value: "Revolut",
    ParserKey.ETORO_ACTIVITY.value: "eToro",
    ParserKey.ETORO_ACCOUNT_STATEMENT.value: "eToro",
}


def _decode_text(file_bytes: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1250", "latin-1"):
        try:
            return file_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    return file_bytes.decode("utf-8", errors="replace")


def _first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line
    return ""


def _normalize_headers(headers: Iterable[str]) -> set[str]:
    out: set[str] = set()
    for h in headers:
        if h is None:
            continue
        name = str(h).replace("\ufeff", "").strip().lower()
        if name:
            out.add(name)
    return out


def _score(headers: set[str], markers: set[str]) -> int:
    return sum(1 for m in markers if m in headers)


def _sniff_headers(text: str) -> tuple[set[str], str]:
    """
    Return (header_set, delimiter_guess).

    Tries semicolon first when present on the header line (Raiffeisen).
    """
    header_line = _first_line(text)
    if not header_line:
        return set(), ","

    if header_line.count(";") >= header_line.count(","):
        delim = ";"
    else:
        delim = ","

    reader = csv.reader(io.StringIO(header_line), delimiter=delim)
    try:
        row = next(reader)
    except StopIteration:
        return set(), delim
    return _normalize_headers(row), delim


def detect_parser_key(file_bytes: bytes) -> str:
    """
    Detect which parser should handle this file.

    Returns a ``ParserKey`` value string, e.g. ``raiffeisen_cz``.
    Raises ``ValueError`` if unrecognized.
    """
    # Binary Excel first (eToro official account statement)
    if file_bytes[:2] == _XLSX_MAGIC:
        from backend.parsers.etoro_account_statement import is_etoro_account_statement_xlsx

        if is_etoro_account_statement_xlsx(file_bytes):
            return ParserKey.ETORO_ACCOUNT_STATEMENT.value
        raise ValueError(
            "unrecognized .xlsx statement; expected eToro Account Statement "
            "with an 'Account Activity' sheet"
        )

    text = _decode_text(file_bytes)
    headers, _delim = _sniff_headers(text)
    if not headers:
        raise ValueError("empty or headerless statement file")

    scores = {
        ParserKey.RAIFFEISEN_CZ.value: _score(headers, _RAIFFEISEN_MARKERS),
        ParserKey.REVOLUT_EXPENSES.value: _score(headers, _REVOLUT_EXPENSES_MARKERS),
        ParserKey.REVOLUT_CRYPTO.value: _score(headers, _REVOLUT_CRYPTO_MARKERS),
        ParserKey.REVOLUT_STOCKS.value: _score(headers, _REVOLUT_STOCKS_MARKERS),
        ParserKey.ETORO_ACTIVITY.value: _score(headers, _ETORO_MARKERS),
    }

    # Disambiguation: crypto has Symbol+Fees; stocks has Ticker+FX Rate; expenses has State+Balance
    if "fx rate" in headers and "ticker" in headers:
        scores[ParserKey.REVOLUT_STOCKS.value] += 3
    if "symbol" in headers and "fees" in headers and "price per share" not in headers:
        scores[ParserKey.REVOLUT_CRYPTO.value] += 3
    if "state" in headers and "balance" in headers and "product" in headers:
        scores[ParserKey.REVOLUT_EXPENSES.value] += 3
    if "eventtype" in headers or "platform" in headers:
        scores[ParserKey.ETORO_ACTIVITY.value] += 3
    if "booked amount" in headers or "transaction id" in headers:
        scores[ParserKey.RAIFFEISEN_CZ.value] += 3

    best_key = max(scores, key=scores.get)
    best_score = scores[best_key]
    # Require a minimum confidence
    if best_score < 4:
        raise ValueError(
            f"unrecognized statement format; header scores={scores}; headers={sorted(headers)}"
        )
    return best_key


def detect_institution(file_bytes: bytes) -> str:
    """
    Auto-detect institution label from file headers/content.

    For multi-format brokers (Revolut), still returns ``Revolut``; use
    :func:`detect_parser_key` to select the concrete parser.
    """
    key = detect_parser_key(file_bytes)
    return _PARSER_TO_INSTITUTION[key]


def institution_for_parser_key(parser_key: str) -> str:
    try:
        return _PARSER_TO_INSTITUTION[parser_key]
    except KeyError as exc:
        raise ValueError(f"unknown parser_key: {parser_key!r}") from exc


def decode_statement_text(file_bytes: bytes) -> str:
    """Public decode helper (BOM-aware)."""
    return _decode_text(file_bytes)
