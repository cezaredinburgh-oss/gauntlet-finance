from __future__ import annotations

from pathlib import Path

import pytest

from backend.parsers.detect import detect_institution, detect_parser_key
from backend.schema.models import ParserKey

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize(
    "filename,parser_key,institution",
    [
        ("raiffeisen_sample.csv", ParserKey.RAIFFEISEN_CZ.value, "Raiffeisen"),
        ("revolut_expenses_sample.csv", ParserKey.REVOLUT_EXPENSES.value, "Revolut"),
        ("revolut_crypto_sample.csv", ParserKey.REVOLUT_CRYPTO.value, "Revolut"),
        ("revolut_stocks_sample.csv", ParserKey.REVOLUT_STOCKS.value, "Revolut"),
        ("etoro_sample.csv", ParserKey.ETORO_ACTIVITY.value, "eToro"),
        (
            "etoro_account_statement_sample.xlsx",
            ParserKey.ETORO_ACCOUNT_STATEMENT.value,
            "eToro",
        ),
    ],
)
def test_detect_fixtures(filename: str, parser_key: str, institution: str):
    data = (FIXTURES / filename).read_bytes()
    assert detect_parser_key(data) == parser_key
    assert detect_institution(data) == institution


def test_detect_unknown_raises():
    with pytest.raises(ValueError, match="unrecognized"):
        detect_parser_key(b"foo,bar\n1,2\n")
