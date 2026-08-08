"""
Statement parsers and institution auto-detection.

Public API for the next FastAPI phase::

    from backend.parsers import (
        detect_institution,
        detect_parser_key,
        parse_statement_bytes,
        parse_raiffeisen,
        parse_revolut_expenses,
        parse_revolut_crypto,
        parse_revolut_stocks,
        parse_etoro,
    )
"""

from backend.parsers.detect import detect_institution, detect_parser_key
from backend.parsers.etoro import parse_etoro, parse_etoro_bytes
from backend.parsers.import_file import (
    build_statement_file_row,
    parse_statement_bytes,
)
from backend.parsers.raiffeisen import parse_raiffeisen, parse_raiffeisen_bytes
from backend.parsers.revolut_crypto import parse_revolut_crypto, parse_revolut_crypto_bytes
from backend.parsers.revolut_expenses import (
    parse_revolut_expenses,
    parse_revolut_expenses_bytes,
)
from backend.parsers.revolut_stocks import parse_revolut_stocks, parse_revolut_stocks_bytes

__all__ = [
    "detect_institution",
    "detect_parser_key",
    "parse_statement_bytes",
    "build_statement_file_row",
    "parse_raiffeisen",
    "parse_raiffeisen_bytes",
    "parse_revolut_expenses",
    "parse_revolut_expenses_bytes",
    "parse_revolut_crypto",
    "parse_revolut_crypto_bytes",
    "parse_revolut_stocks",
    "parse_revolut_stocks_bytes",
    "parse_etoro",
    "parse_etoro_bytes",
]
