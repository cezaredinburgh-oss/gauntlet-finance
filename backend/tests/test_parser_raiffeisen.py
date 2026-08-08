from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from backend.parsers.raiffeisen import parse_raiffeisen

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_raiffeisen_spotify_allianz_revolut_inbound():
    text = (FIXTURES / "raiffeisen_sample.csv").read_text(encoding="utf-8")
    account_id = uuid4()
    result = parse_raiffeisen(
        text,
        account_ids={"CZK": account_id, "default": account_id},
        source_file_id=uuid4(),
        file_hash="a" * 64,
    )
    assert result.parser_key == "raiffeisen_cz"
    assert result.row_count == 4
    assert len(result.transactions) == 4

    by_merchant = {t.merchant: t for t in result.transactions if t.merchant}
    assert by_merchant["Spotify"].amount == Decimal("-185")
    assert by_merchant["Spotify"].currency == "CZK"
    assert by_merchant["Spotify"].external_id == "9295911738"
    assert by_merchant["Spotify"].booking_date.isoformat() == "2026-07-30"
    assert by_merchant["Spotify"].value_date.isoformat() == "2026-07-28"

    allianz = by_merchant["Allianz"]
    assert allianz.amount == Decimal("-1887")

    inbound = [
        t
        for t in result.transactions
        if t.amount > 0 and t.original_description and "Revolut" in t.original_description
    ]
    assert len(inbound) == 1
    assert inbound[0].amount == Decimal("10000")
    assert inbound[0].counterparty_account == "2001141349/0800"
    assert inbound[0].source_institution == "Raiffeisen"
    assert inbound[0].original_file_hash == "a" * 64
