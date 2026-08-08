from __future__ import annotations

from backend.services.import_pipeline import (
    _build_import_message,
    _filename_parser_hint,
)


def test_build_import_message_tx_only():
    msg = _build_import_message(
        parser_key="revolut_expenses",
        filename="Tax year test Revolut checking account.csv",
        rows_parsed=2200,
        transactions_written=59,
        events_written=0,
        transactions_deduped=2128,
        events_deduped=0,
    )
    assert msg == (
        "[revolut_expenses] 2187 parsed · 2128 already in ledger · 59 new"
    )


def test_build_import_message_events_only():
    msg = _build_import_message(
        parser_key="revolut_crypto",
        filename="Tax year test Revolut crypto_.csv",
        rows_parsed=400,
        transactions_written=0,
        events_written=3,
        transactions_deduped=0,
        events_deduped=385,
    )
    assert msg == (
        "[revolut_crypto] 388 events · 385 already in ledger · 3 new"
    )


def test_build_import_message_empty():
    msg = _build_import_message(
        parser_key=None,
        filename="empty.csv",
        rows_parsed=0,
        transactions_written=0,
        events_written=0,
        transactions_deduped=0,
        events_deduped=0,
    )
    assert msg == "0 rows parsed · nothing new"


def test_filename_parser_hint_mismatch():
    hint = _filename_parser_hint(
        "Tax year test Revolut crypto_.csv",
        "revolut_expenses",
    )
    assert hint is not None
    assert "revolut_crypto" in hint
    assert "revolut_expenses" in hint


def test_filename_parser_hint_match_is_silent():
    assert (
        _filename_parser_hint(
            "Tax year test Revolut crypto_.csv",
            "revolut_crypto",
        )
        is None
    )
