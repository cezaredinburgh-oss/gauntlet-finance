"""
Integration check: parse all Bank statements/*.csv files.

Verifies:
  1. Auto-detect succeeds for all five formats
  2. Parse completes without error
  3. Transaction / InvestmentEvent / Lot counts are consistent
  4. Re-parsing the same bytes with the hash is a no-op
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from uuid import uuid4

from backend.common.hashing import sha256_hex
from backend.parsers import detect_institution, detect_parser_key, parse_statement_bytes

ROOT = Path(__file__).resolve().parents[2]
BANK = ROOT / "Bank statements"

# Broad currency map so multi-currency Revolut expenses never KeyError
ACCOUNTS = {
    "default": uuid4(),
    **{ccy: uuid4() for ccy in (
        "CZK", "USD", "EUR", "GBP", "INR", "PLN", "CHF", "RON", "HUF",
        "SEK", "DKK", "NOK", "AUD", "CAD", "JPY", "SGD", "HKD", "TRY",
        "AED", "MXN", "BRL", "NZD", "THB", "ILS", "ZAR", "RUB", "CNY",
    )},
}


def main() -> int:
    files = sorted(BANK.glob("*.csv"))
    print("=" * 88)
    print(f"Found {len(files)} CSV files in {BANK}")
    print("=" * 88)

    results: list[dict] = []
    errors: list[tuple[str, str]] = []

    for path in files:
        data = path.read_bytes()
        try:
            key = detect_parser_key(data)
            inst = detect_institution(data)
            parsed = parse_statement_bytes(
                data,
                account_ids=ACCOUNTS,
                filename=path.name,
            )
            type_counts = Counter(
                e.event_type.value for e in parsed.investment_events
            )
            results.append(
                {
                    "name": path.name,
                    "sha16": sha256_hex(data)[:16],
                    "parser_key": key,
                    "institution": inst,
                    "status": parsed.status,
                    "row_count": parsed.row_count,
                    "tx": len(parsed.transactions),
                    "events": len(parsed.investment_events),
                    "lots": len(parsed.investment_lots),
                    "event_types": dict(type_counts),
                    "content_sha256": parsed.content_sha256,
                }
            )
        except Exception as exc:  # noqa: BLE001 — report all failures
            errors.append((path.name, repr(exc)))
            results.append({"name": path.name, "error": repr(exc)})

    hdr = f"{'File':<42} {'Parser':<18} {'Status':<10} {'Rows':>6} {'Tx':>6} {'Events':>7} {'Lots':>6}"
    print(hdr)
    print("-" * len(hdr))
    for r in results:
        if "error" in r:
            print(f"{r['name']:<42} ERROR: {r['error']}")
        else:
            print(
                f"{r['name'][:42]:<42} {r['parser_key']:<18} {r['status']:<10} "
                f"{r['row_count']:>6} {r['tx']:>6} {r['events']:>7} {r['lots']:>6}"
            )

    print()
    print("Event type breakdown (investment files):")
    for r in results:
        if r.get("event_types"):
            print(f"  {r['name']}: {r['event_types']}")

    print()
    print("=" * 88)
    print("Idempotency: re-parse same bytes with existing hash → already_imported")
    print("=" * 88)

    idempotent_ok = True
    for path in files:
        data = path.read_bytes()
        h = sha256_hex(data)
        first = parse_statement_bytes(
            data, account_ids=ACCOUNTS, filename=path.name
        )
        second = parse_statement_bytes(
            data,
            account_ids=ACCOUNTS,
            filename=path.name,
            existing_hashes={h},
        )
        third = parse_statement_bytes(
            data,
            account_ids=ACCOUNTS,
            existing_hashes={first.content_sha256},
        )
        ok = (
            first.status == "parsed"
            and second.status == "already_imported"
            and third.status == "already_imported"
            and second.transactions == []
            and second.investment_events == []
            and second.investment_lots == []
            and second.message == "already imported"
            and second.content_sha256 == h
            and len(second.transactions) == 0
        )
        if not ok:
            idempotent_ok = False
        mark = "OK" if ok else "FAIL"
        print(
            f"  {mark}  {path.name[:40]:<40} first={first.status} "
            f"reparse={second.status} "
            f"tx={len(second.transactions)} "
            f"ev={len(second.investment_events)} "
            f"lots={len(second.investment_lots)}"
        )

    print()
    print("=" * 88)
    print("Sanity checks")
    print("=" * 88)

    by_key = {r["parser_key"]: r for r in results if "error" not in r}
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        checks.append((name, cond, detail))

    expected_keys = {
        "raiffeisen_cz",
        "revolut_expenses",
        "revolut_crypto",
        "revolut_stocks",
        "etoro_activity",
    }
    found_keys = set(by_key)
    check(
        "all five parser keys detected",
        expected_keys <= found_keys,
        f"found={sorted(found_keys)}",
    )
    check("zero parse exceptions", len(errors) == 0, str(errors))

    if "raiffeisen_cz" in by_key:
        r = by_key["raiffeisen_cz"]
        check(
            "Raiffeisen tx == row_count",
            r["tx"] == r["row_count"] and r["tx"] > 0,
            f"tx={r['tx']} rows={r['row_count']}",
        )
        check(
            "Raiffeisen no investment rows",
            r["events"] == 0 and r["lots"] == 0,
        )

    if "revolut_expenses" in by_key:
        r = by_key["revolut_expenses"]
        check(
            "Revolut expenses tx <= rows (REVERTED skipped)",
            0 < r["tx"] <= r["row_count"],
            f"tx={r['tx']} rows={r['row_count']}",
        )
        check(
            "Revolut expenses cash-only",
            r["events"] == 0 and r["lots"] == 0,
        )

    if "revolut_crypto" in by_key:
        r = by_key["revolut_crypto"]
        check(
            "Revolut crypto events == rows",
            r["events"] == r["row_count"],
            f"ev={r['events']} rows={r['row_count']}",
        )
        check(
            "Revolut crypto lots > 0 and <= events",
            0 < r["lots"] <= r["events"],
            f"lots={r['lots']}",
        )
        check(
            "Revolut crypto has Buy and StakingReward",
            "Buy" in r["event_types"] and "StakingReward" in r["event_types"],
            str(r["event_types"]),
        )
        # Lots = Buy + StakingReward only
        openers = r["event_types"].get("Buy", 0) + r["event_types"].get(
            "StakingReward", 0
        )
        check(
            "Revolut crypto lots == Buy+StakingReward",
            r["lots"] == openers,
            f"lots={r['lots']} openers={openers}",
        )

    if "revolut_stocks" in by_key:
        r = by_key["revolut_stocks"]
        check(
            "Revolut stocks events == rows",
            r["events"] == r["row_count"],
            f"ev={r['events']} rows={r['row_count']}",
        )
        check(
            "Revolut stocks has Transfer + Buy",
            "Transfer" in r["event_types"] and "Buy" in r["event_types"],
            str(r["event_types"]),
        )
        buy_n = r["event_types"].get("Buy", 0)
        check(
            "Revolut stocks lots == Buy count",
            r["lots"] == buy_n,
            f"lots={r['lots']} buys={buy_n}",
        )
        check(
            "Revolut stocks has Split",
            "Split" in r["event_types"],
            str(r["event_types"]),
        )

    if "etoro_activity" in by_key:
        r = by_key["etoro_activity"]
        check(
            "eToro events == rows",
            r["events"] == r["row_count"],
            f"ev={r['events']} rows={r['row_count']}",
        )
        check(
            "eToro has Fee (Commission)",
            "Fee" in r["event_types"],
            str(r["event_types"]),
        )
        openers = r["event_types"].get("Buy", 0) + r["event_types"].get(
            "StakingReward", 0
        )
        check(
            "eToro lots == Buy+StakingReward",
            r["lots"] == openers,
            f"lots={r['lots']} openers={openers}",
        )

    check("idempotent re-parse all files", idempotent_ok)

    all_ok = True
    for name, cond, detail in checks:
        mark = "PASS" if cond else "FAIL"
        if not cond:
            all_ok = False
        extra = f"  ({detail})" if detail else ""
        print(f"  [{mark}] {name}{extra}")

    print()
    print("=" * 88)
    if all_ok and not errors:
        print("RESULT: ALL CHECKS PASSED")
        return 0

    print("RESULT: SOME CHECKS FAILED")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
