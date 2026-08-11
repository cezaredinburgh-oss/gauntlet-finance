"""
FIFO lot / cost-basis engine with Czech 3-year holding helpers.

Processes investment events into open lots and LotAllocation children.
Does not mutate inputs; returns updated lots + events.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID, uuid4

from backend.common.timeutil import utc_now
from backend.engines.fx import FXService
from backend.schema.models import (
    AssetClass,
    InvestmentEvent,
    InvestmentEventType,
    InvestmentLot,
    LotStatus,
    TradeSide,
)

DEFAULT_EXEMPTION_DAYS = 1095  # 3 * 365 (schema Settings default)


def _q(value: Decimal, places: str = "0.00000001") -> Decimal:
    return value.quantize(Decimal(places), rounding=ROUND_HALF_UP)


def _q2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _event_sort_key(e: InvestmentEvent) -> tuple:
    """Sort key using timezone-aware UTC datetimes only."""
    from datetime import timezone

    dt = e.event_datetime
    if dt is not None:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
    else:
        dt = datetime(e.event_date.year, e.event_date.month, e.event_date.day, tzinfo=timezone.utc)
    return (dt, e.event_date, str(e.id))


@dataclass
class LotEligibility:
    lot_id: UUID
    ticker: str
    quantity_remaining: Decimal
    acquisition_date: date
    tax_free_on: date
    holding_period_days: int
    qualifies_3y_exemption: bool
    cost_basis_native: Decimal
    cost_basis_czk: Decimal
    cost_basis_usd: Decimal
    native_currency: str


@dataclass
class TickerPositionSummary:
    ticker: str
    total_quantity: Decimal
    quantity_tax_free: Decimal
    quantity_pending: Decimal
    cost_basis_native: Decimal
    cost_basis_czk: Decimal
    cost_basis_usd: Decimal
    native_currency: str | None
    market_value_native: Decimal | None
    unrealized_pnl_native: Decimal | None
    lots: list[LotEligibility] = field(default_factory=list)
    as_of: date = field(default_factory=date.today)
    exemption_days: int = DEFAULT_EXEMPTION_DAYS


@dataclass
class FifoResult:
    lots: list[InvestmentLot]
    events: list[InvestmentEvent]
    allocations_created: int = 0


class LotEngine:
    """
    Maintain InvestmentLots with FIFO relief (specific lot_id on event wins).

    Optional ``fx`` enriches CZK/USD cost and gains when rates are available.
    """

    def __init__(
        self,
        *,
        fx: FXService | None = None,
        exemption_days: int = DEFAULT_EXEMPTION_DAYS,
    ) -> None:
        self.fx = fx
        self.exemption_days = exemption_days

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def apply_events(
        self,
        existing_lots: list[InvestmentLot],
        new_events: list[InvestmentEvent],
        *,
        now: datetime | None = None,
    ) -> FifoResult:
        """
        Apply ``new_events`` chronologically against a copy of ``existing_lots``.

        - Buy / StakingReward → open lot (if not already linked)
        - Sell → FIFO (or specific lot_id) LotAllocation children + reduce lots
        - Fee with parent Buy → capitalize into that lot when still open
        - Split → scale quantities for ticker; total cost unchanged
        - Transfer out with quantity → reduce/close lots FIFO, mark TransferredOut
        - Stake / Deposit / Withdrawal → pass-through (no lot qty change by default)
        """
        ts = now or utc_now()
        lots: dict[UUID, InvestmentLot] = {
            lot.id: lot.model_copy(deep=True) for lot in existing_lots
        }
        # Preserve pre-existing events not in new_events — only return updated set
        # for lots + the new_events with allocations appended.
        out_events: list[InvestmentEvent] = []
        allocations = 0

        ordered = sorted(new_events, key=_event_sort_key)
        # Map buy event id -> lot id for fee capitalization
        buy_event_to_lot: dict[UUID, UUID] = {
            lot.open_event_id: lot.id
            for lot in lots.values()
            if lot.open_event_id is not None
        }

        for ev in ordered:
            e = ev.model_copy(deep=True)

            if e.event_type in {
                InvestmentEventType.BUY,
                InvestmentEventType.STAKING_REWARD,
            }:
                e, new_lot = self._open_from_event(e, lots, ts)
                if new_lot is not None:
                    lots[new_lot.id] = new_lot
                    buy_event_to_lot[e.id] = new_lot.id
                out_events.append(e)

            elif e.event_type == InvestmentEventType.SELL:
                e, allocs, lots = self._allocate_sell(e, lots, ts)
                out_events.append(e)
                out_events.extend(allocs)
                allocations += len(allocs)

            elif e.event_type == InvestmentEventType.FEE:
                e, lots = self._apply_fee(e, lots, buy_event_to_lot, ts)
                out_events.append(e)

            elif e.event_type == InvestmentEventType.SPLIT:
                e, lots = self._apply_split(e, lots, ts)
                out_events.append(e)

            elif e.event_type == InvestmentEventType.TRANSFER:
                # Broker legal-entity migrations keep inventory; only real
                # outbound transfers reduce lots (see _is_inventory_exit_transfer).
                if self._is_inventory_exit_transfer(e):
                    e, allocs, lots = self._apply_transfer(e, lots, ts)
                    out_events.append(e)
                    out_events.extend(allocs)
                    allocations += len(allocs)
                else:
                    e = e.model_copy(
                        update={
                            "notes": (
                                ((e.notes + "; ") if e.notes else "")
                                + "legal_entity_transfer_no_inventory_change"
                            ).strip("; ")
                        }
                    )
                    out_events.append(e)

            else:
                # Stake, Deposit, Withdrawal, LotAllocation (if re-fed): keep as-is
                out_events.append(e)

        return FifoResult(
            lots=list(lots.values()),
            events=out_events,
            allocations_created=allocations,
        )

    def summarize_ticker(
        self,
        lots: list[InvestmentLot],
        ticker: str,
        *,
        as_of: date | None = None,
        market_price_native: Decimal | None = None,
        exemption_days: int | None = None,
    ) -> TickerPositionSummary:
        """
        Position snapshot for a ticker: qty, tax-free qty, per-lot free dates,
        cost basis, optional unrealized P&L when price supplied.
        """
        as_of = as_of or date.today()
        days = exemption_days if exemption_days is not None else self.exemption_days
        t = ticker.upper()
        open_lots = [
            lot
            for lot in lots
            if lot.ticker.upper() == t
            and lot.status == LotStatus.OPEN
            and lot.quantity_remaining > 0
            and not lot.archived
        ]
        open_lots.sort(key=lambda x: (x.acquisition_date, str(x.id)))

        elig: list[LotEligibility] = []
        total_q = Decimal("0")
        tax_free_q = Decimal("0")
        cost_n = Decimal("0")
        cost_czk = Decimal("0")
        cost_usd = Decimal("0")
        native_ccy: str | None = None

        for lot in open_lots:
            held = (as_of - lot.acquisition_date).days
            free_on = lot.acquisition_date + timedelta(days=days)
            qualifies = held >= days
            elig.append(
                LotEligibility(
                    lot_id=lot.id,
                    ticker=lot.ticker,
                    quantity_remaining=lot.quantity_remaining,
                    acquisition_date=lot.acquisition_date,
                    tax_free_on=free_on,
                    holding_period_days=held,
                    qualifies_3y_exemption=qualifies,
                    cost_basis_native=lot.cost_basis_native,
                    cost_basis_czk=lot.cost_basis_czk,
                    cost_basis_usd=lot.cost_basis_usd,
                    native_currency=lot.native_currency,
                )
            )
            total_q += lot.quantity_remaining
            if qualifies:
                tax_free_q += lot.quantity_remaining
            cost_n += lot.cost_basis_native
            cost_czk += lot.cost_basis_czk
            cost_usd += lot.cost_basis_usd
            native_ccy = native_ccy or lot.native_currency

        mv = None
        upnl = None
        if market_price_native is not None and total_q > 0:
            mv = _q2(total_q * market_price_native)
            upnl = _q2(mv - cost_n)

        return TickerPositionSummary(
            ticker=t,
            total_quantity=total_q,
            quantity_tax_free=tax_free_q,
            quantity_pending=total_q - tax_free_q,
            cost_basis_native=cost_n,
            cost_basis_czk=cost_czk,
            cost_basis_usd=cost_usd,
            native_currency=native_ccy,
            market_value_native=mv,
            unrealized_pnl_native=upnl,
            lots=elig,
            as_of=as_of,
            exemption_days=days,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _enrich_cost(
        self,
        cost_native: Decimal,
        currency: str,
        on: date,
    ) -> tuple[Decimal, Decimal, Decimal]:
        ccy = (currency or "USD").upper()
        czk = Decimal("0")
        usd = Decimal("0")
        if ccy == "CZK":
            czk = cost_native
        elif ccy == "USD":
            usd = cost_native
        if self.fx is not None:
            if ccy != "CZK":
                conv = self.fx.convert(cost_native, ccy, "CZK", on)
                if conv is not None:
                    czk = conv
            else:
                czk = cost_native
            if ccy != "USD":
                conv_u = self.fx.convert(cost_native, ccy, "USD", on)
                if conv_u is not None:
                    usd = conv_u
            else:
                usd = cost_native
        else:
            if ccy == "CZK":
                czk = cost_native
            if ccy == "USD":
                usd = cost_native
        return cost_native, czk, usd

    def _open_from_event(
        self,
        e: InvestmentEvent,
        lots: dict[UUID, InvestmentLot],
        ts: datetime,
    ) -> tuple[InvestmentEvent, InvestmentLot | None]:
        if e.lot_id and e.lot_id in lots:
            return e, None
        if not e.ticker or e.quantity is None or e.quantity <= 0:
            return e, None

        fees = e.fees_native or Decimal("0")
        value = e.value_native if e.value_native is not None else Decimal("0")
        # For buys, cost = value + fees (fees may be separate Fee event later)
        cost = value + fees
        if cost < 0:
            cost = abs(cost)

        ccy = (e.native_currency or "USD").upper()
        native, czk, usd = self._enrich_cost(cost, ccy, e.event_date)
        lot_id = e.lot_id or uuid4()
        asset = e.asset_class or AssetClass.OTHER
        lot = InvestmentLot(
            id=lot_id,
            account_id=e.account_id,
            ticker=e.ticker,
            asset_class=asset,
            source=e.source,
            acquisition_date=e.event_date,
            quantity_opened=e.quantity,
            quantity_remaining=e.quantity,
            cost_basis_native=native,
            cost_basis_czk=czk,
            cost_basis_usd=usd,
            native_currency=ccy,
            open_event_id=e.id,
            status=LotStatus.OPEN,
            created_at=ts,
            updated_at=ts,
        )
        e = e.model_copy(update={"lot_id": lot_id})
        return e, lot

    def _open_lots_for_ticker(
        self,
        lots: dict[UUID, InvestmentLot],
        ticker: str,
        account_id: UUID | None = None,
    ) -> list[InvestmentLot]:
        t = ticker.upper()
        open_lots = [
            lot
            for lot in lots.values()
            if lot.ticker.upper() == t
            and lot.status == LotStatus.OPEN
            and lot.quantity_remaining > 0
            and not lot.archived
            and (account_id is None or lot.account_id == account_id)
        ]
        open_lots.sort(key=lambda x: (x.acquisition_date, str(x.id)))
        return open_lots

    def _allocate_sell(
        self,
        sell: InvestmentEvent,
        lots: dict[UUID, InvestmentLot],
        ts: datetime,
    ) -> tuple[InvestmentEvent, list[InvestmentEvent], dict[UUID, InvestmentLot]]:
        if not sell.ticker or sell.quantity is None or sell.quantity <= 0:
            return sell, [], lots

        qty_need = sell.quantity
        proceeds = sell.value_native if sell.value_native is not None else Decimal("0")
        fees = sell.fees_native or Decimal("0")
        net_proceeds = proceeds - abs(fees)
        ccy = (sell.native_currency or "USD").upper()

        # Specific identification if sell.lot_id set
        if sell.lot_id and sell.lot_id in lots:
            candidates = [lots[sell.lot_id]]
        else:
            candidates = self._open_lots_for_ticker(lots, sell.ticker, sell.account_id)
            if not candidates:
                # fallback any account
                candidates = self._open_lots_for_ticker(lots, sell.ticker, None)

        allocs: list[InvestmentEvent] = []
        remaining = qty_need
        total_qty = qty_need

        for lot in candidates:
            if remaining <= 0:
                break
            if lot.quantity_remaining <= 0:
                continue
            take = min(lot.quantity_remaining, remaining)
            if take <= 0:
                continue

            frac_lot = take / lot.quantity_remaining if lot.quantity_remaining else Decimal("0")
            cost_n = _q2(lot.cost_basis_native * frac_lot)
            cost_czk = _q2(lot.cost_basis_czk * frac_lot)
            cost_usd = _q2(lot.cost_basis_usd * frac_lot)

            # Proceeds share by qty of sell
            frac_sell = take / total_qty if total_qty else Decimal("0")
            proc_share = _q2(net_proceeds * frac_sell)

            # Do not invent FX: leave CZK/USD proceeds None when convert fails
            # (and native ccy is neither). Avoids phantom losses of 0 - cost.
            proc_czk: Decimal | None = None
            proc_usd: Decimal | None = None
            if ccy == "CZK":
                proc_czk = proc_share
            elif self.fx is not None:
                pc = self.fx.convert(proc_share, ccy, "CZK", sell.event_date)
                if pc is not None:
                    proc_czk = pc
            if ccy == "USD":
                proc_usd = proc_share
            elif self.fx is not None:
                pu = self.fx.convert(proc_share, ccy, "USD", sell.event_date)
                if pu is not None:
                    proc_usd = pu

            gain_czk = _q2(proc_czk - cost_czk) if proc_czk is not None else None
            gain_usd = _q2(proc_usd - cost_usd) if proc_usd is not None else None
            # Native gain always computable
            gain_native = _q2(proc_share - cost_n)

            held = (sell.event_date - lot.acquisition_date).days
            qualifies = held >= self.exemption_days

            # Reduce lot
            new_rem = lot.quantity_remaining - take
            new_cost_n = lot.cost_basis_native - cost_n
            new_cost_czk = lot.cost_basis_czk - cost_czk
            new_cost_usd = lot.cost_basis_usd - cost_usd
            if new_rem <= 0:
                status = LotStatus.CLOSED
                new_rem = Decimal("0")
                new_cost_n = new_cost_czk = new_cost_usd = Decimal("0")
            else:
                status = LotStatus.OPEN

            lots[lot.id] = lot.model_copy(
                update={
                    "quantity_remaining": new_rem,
                    "cost_basis_native": max(new_cost_n, Decimal("0")),
                    "cost_basis_czk": max(new_cost_czk, Decimal("0")),
                    "cost_basis_usd": max(new_cost_usd, Decimal("0")),
                    "status": status,
                    "updated_at": ts,
                }
            )

            alloc = InvestmentEvent(
                id=uuid4(),
                account_id=sell.account_id,
                event_type=InvestmentEventType.LOT_ALLOCATION,
                event_date=sell.event_date,
                event_datetime=sell.event_datetime,
                ticker=sell.ticker,
                asset_class=sell.asset_class or lot.asset_class,
                side=TradeSide.SELL,
                quantity=take,
                price_native=sell.price_native,
                native_currency=ccy,
                value_native=proc_share,
                fees_native=Decimal("0"),
                # Keep zero proceeds when legitimately zero; only None if unknown
                value_czk=proc_czk,
                value_usd=proc_usd,
                lot_id=lot.id,
                parent_event_id=sell.id,
                realized_gain_czk=gain_czk,
                realized_gain_usd=gain_usd,
                holding_period_days=held,
                qualifies_3y_exemption=qualifies,
                source=sell.source,
                description=f"FIFO allocation {take} {sell.ticker} (native gain {gain_native})",
                source_file_id=sell.source_file_id,
                original_file_hash=sell.original_file_hash,
                created_at=ts,
                updated_at=ts,
            )
            allocs.append(alloc)
            remaining -= take

        # H5: surface short-sell / unallocated remainder instead of silent drop
        if remaining > 0:
            note_bits: list[str] = []
            if sell.notes:
                note_bits.append(sell.notes)
            note_bits.append(f"unallocated_qty={remaining}")
            note_bits.append("short_sell_unallocated")
            sell = sell.model_copy(update={"notes": "; ".join(note_bits)})

        return sell, allocs, lots

    def _apply_fee(
        self,
        fee: InvestmentEvent,
        lots: dict[UUID, InvestmentLot],
        buy_event_to_lot: dict[UUID, UUID],
        ts: datetime,
    ) -> tuple[InvestmentEvent, dict[UUID, InvestmentLot]]:
        parent = fee.parent_event_id
        lot_id = None
        if parent and parent in buy_event_to_lot:
            lot_id = buy_event_to_lot[parent]
        elif fee.lot_id:
            lot_id = fee.lot_id

        if lot_id and lot_id in lots:
            lot = lots[lot_id]
            if lot.status == LotStatus.OPEN:
                fee_abs = abs(fee.value_native or fee.fees_native or Decimal("0"))
                lot_ccy = (lot.native_currency or "USD").upper()
                fee_ccy = (fee.native_currency or lot_ccy).upper()

                if fee_ccy == lot_ccy:
                    add_n, add_czk, add_usd = self._enrich_cost(
                        fee_abs, lot_ccy, fee.event_date
                    )
                else:
                    # H6: never add a foreign-currency number into cost_basis_native.
                    # Prefer FX into lot native; if convert fails, add_n=0 and only
                    # enrich CZK/USD legs from the fee's own currency.
                    converted: Decimal | None = None
                    if self.fx is not None:
                        converted = self.fx.convert(
                            fee_abs, fee_ccy, lot_ccy, fee.event_date
                        )
                    if converted is not None:
                        add_n, add_czk, add_usd = self._enrich_cost(
                            converted, lot_ccy, fee.event_date
                        )
                    else:
                        add_n = Decimal("0")
                        _, add_czk, add_usd = self._enrich_cost(
                            fee_abs, fee_ccy, fee.event_date
                        )

                lots[lot_id] = lot.model_copy(
                    update={
                        "cost_basis_native": lot.cost_basis_native + add_n,
                        "cost_basis_czk": lot.cost_basis_czk + add_czk,
                        "cost_basis_usd": lot.cost_basis_usd + add_usd,
                        "updated_at": ts,
                    }
                )
                fee = fee.model_copy(update={"lot_id": lot_id, "parent_event_id": parent})
        return fee, lots

    def _apply_split(
        self,
        split: InvestmentEvent,
        lots: dict[UUID, InvestmentLot],
        ts: datetime,
    ) -> tuple[InvestmentEvent, dict[UUID, InvestmentLot]]:
        """
        Stock split / reverse split.

        Revolut exports ``quantity`` as a **signed share delta** (not a
        post-split absolute total):

        - ``quantity > 0``: shares **added** (forward split). Example: TSLA
          3-for-1 with pre-split 4.878… and qty 9.756… → new total 14.635…
          (pre + delta). Total cost basis is **unchanged** (par value
          redistributed across more shares).
        - ``quantity < 0``: shares **removed** (reverse / consolidation).
          Cost totals scale down with remaining quantity.
        - ``quantity == 0`` or missing: no-op.

        When ``split.source`` is set, only open lots with that source are
        scaled (avoids Revolut splits touching eToro inventory).
        """
        if not split.ticker or split.quantity is None or split.quantity == 0:
            return split, lots

        open_lots = self._open_lots_for_ticker(lots, split.ticker, split.account_id)
        if not open_lots:
            open_lots = self._open_lots_for_ticker(lots, split.ticker, None)
        if not open_lots:
            return split, lots

        # Prefer same broker/source when present (multi-platform safety)
        src = (split.source or "").strip()
        if src:
            sourced = [
                lot
                for lot in open_lots
                if (lot.source or "").strip().lower() == src.lower()
            ]
            if sourced:
                open_lots = sourced

        current_total = sum((l.quantity_remaining for l in open_lots), Decimal("0"))
        if current_total <= 0:
            return split, lots

        # Quantity is always a signed delta (forward or reverse)
        target = current_total + split.quantity
        # Reverse splits (qty removed): scale cost with remaining shares.
        # Forward splits: keep total cost, dilute unit cost across more shares.
        scale_cost = split.quantity < 0

        if target <= 0:
            for lot in open_lots:
                lots[lot.id] = lot.model_copy(
                    update={
                        "quantity_remaining": Decimal("0"),
                        "cost_basis_native": Decimal("0"),
                        "cost_basis_czk": Decimal("0"),
                        "cost_basis_usd": Decimal("0"),
                        "status": LotStatus.CLOSED,
                        "updated_at": ts,
                    }
                )
            return split, lots

        ratio = target / current_total
        for lot in open_lots:
            new_rem = _q(lot.quantity_remaining * ratio)
            new_opened = _q(lot.quantity_opened * ratio)
            update: dict = {
                "quantity_remaining": new_rem,
                "quantity_opened": new_opened,
                "updated_at": ts,
            }
            if scale_cost:
                # Reverse split: remaining cost scales with remaining shares
                update["cost_basis_native"] = _q2(lot.cost_basis_native * ratio)
                update["cost_basis_czk"] = _q2(lot.cost_basis_czk * ratio)
                update["cost_basis_usd"] = _q2(lot.cost_basis_usd * ratio)
            if new_rem <= 0:
                update["quantity_remaining"] = Decimal("0")
                update["cost_basis_native"] = Decimal("0")
                update["cost_basis_czk"] = Decimal("0")
                update["cost_basis_usd"] = Decimal("0")
                update["status"] = LotStatus.CLOSED
            lots[lot.id] = lot.model_copy(update=update)
        return split, lots

    @staticmethod
    def _is_inventory_exit_transfer(e: InvestmentEvent) -> bool:
        """
        True only when shares leave the portfolio.

        Revolut rows like ``TRANSFER FROM REVOLUT TRADING LTD TO REVOLUT
        SECURITIES EUROPE UAB`` are legal-entity migrations and must NOT
        zero lots (acquisition dates stay continuous for the 3-year test).
        """
        blob = " ".join(
            filter(
                None,
                [e.description, e.original_description, e.notes],
            )
        ).upper()
        if "TRADING LTD TO REVOLUT SECURITIES" in blob:
            return False
        if "LEGAL_ENTITY" in blob or "LEGAL ENTITY" in blob:
            return False
        if "REVOLUT TRADING" in blob and "REVOLUT SECURITIES" in blob:
            return False
        # Explicit outbound wording
        if any(
            k in blob
            for k in (
                "TRANSFER OUT",
                "WITHDRAW TO",
                "SENT TO EXTERNAL",
                "OFF PLATFORM",
            )
        ):
            return True
        # Default for generic Transfer without exit wording: keep inventory
        return False

    def _apply_transfer(
        self,
        transfer: InvestmentEvent,
        lots: dict[UUID, InvestmentLot],
        ts: datetime,
    ) -> tuple[InvestmentEvent, list[InvestmentEvent], dict[UUID, InvestmentLot]]:
        """
        Real outbound broker transfer: reduce open lots FIFO without realizing
        gain; mark closed lots TransferredOut.
        """
        if not transfer.ticker or transfer.quantity is None or transfer.quantity <= 0:
            return transfer, [], lots

        # No realized gain — just move inventory out
        qty_need = transfer.quantity
        candidates = self._open_lots_for_ticker(lots, transfer.ticker, transfer.account_id)
        if not candidates:
            candidates = self._open_lots_for_ticker(lots, transfer.ticker, None)

        remaining = qty_need
        allocs: list[InvestmentEvent] = []
        for lot in candidates:
            if remaining <= 0:
                break
            take = min(lot.quantity_remaining, remaining)
            if take <= 0:
                continue
            frac = take / lot.quantity_remaining
            cost_n = _q2(lot.cost_basis_native * frac)
            cost_czk = _q2(lot.cost_basis_czk * frac)
            cost_usd = _q2(lot.cost_basis_usd * frac)
            new_rem = lot.quantity_remaining - take
            if new_rem <= 0:
                status = LotStatus.TRANSFERRED_OUT
                new_rem = Decimal("0")
                new_cost_n = new_cost_czk = new_cost_usd = Decimal("0")
            else:
                status = LotStatus.OPEN
                new_cost_n = lot.cost_basis_native - cost_n
                new_cost_czk = lot.cost_basis_czk - cost_czk
                new_cost_usd = lot.cost_basis_usd - cost_usd

            lots[lot.id] = lot.model_copy(
                update={
                    "quantity_remaining": new_rem,
                    "cost_basis_native": max(new_cost_n, Decimal("0")),
                    "cost_basis_czk": max(new_cost_czk, Decimal("0")),
                    "cost_basis_usd": max(new_cost_usd, Decimal("0")),
                    "status": status,
                    "updated_at": ts,
                }
            )
            allocs.append(
                InvestmentEvent(
                    id=uuid4(),
                    account_id=transfer.account_id,
                    event_type=InvestmentEventType.LOT_ALLOCATION,
                    event_date=transfer.event_date,
                    event_datetime=transfer.event_datetime,
                    ticker=transfer.ticker,
                    asset_class=transfer.asset_class or lot.asset_class,
                    quantity=take,
                    native_currency=lot.native_currency,
                    value_native=cost_n,
                    value_czk=cost_czk,
                    value_usd=cost_usd,
                    fees_native=Decimal("0"),
                    lot_id=lot.id,
                    parent_event_id=transfer.id,
                    holding_period_days=(transfer.event_date - lot.acquisition_date).days,
                    qualifies_3y_exemption=None,
                    source=transfer.source,
                    description="Transfer allocation (no realized gain)",
                    notes="transfer_out",
                    created_at=ts,
                    updated_at=ts,
                )
            )
            remaining -= take

        return transfer, allocs, lots
