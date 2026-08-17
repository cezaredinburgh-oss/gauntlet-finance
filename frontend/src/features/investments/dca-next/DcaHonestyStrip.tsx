import { Link } from "react-router-dom";
import type { DcaBoardResponse } from "../../../api/types";

export function DcaHonestyStrip({ board }: { board: DcaBoardResponse }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-1.5 text-[11px] text-ink-muted">
      <span>
        Planning board · does not place trades · rank ≠ advice · Alerts use harder
        gates.
      </span>
      <span className="rounded-md bg-white/5 px-2 py-0.5">
        As of {board.as_of || "—"}
      </span>
      {board.meta.history_available === false ? (
        <span className="rounded-md bg-warn/10 px-2 py-0.5 text-warn">
          History offline — 3M / 52w shown as — · tone cannot be hot
        </span>
      ) : null}
      <Link to="/alerts" className="ml-auto font-medium text-brand hover:underline">
        Alerts →
      </Link>
    </div>
  );
}
