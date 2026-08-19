import { Link } from "react-router-dom";
import { CATEGORIZE_PATH } from "./workspaceMode";

export function CategorizeWindowBar({
  title,
  honesty,
  backToWindowLabel,
  onBackToWindow,
  onHub,
}: {
  title: string;
  honesty?: string;
  backToWindowLabel?: string | null;
  onBackToWindow?: () => void;
  onHub?: () => void;
}) {
  return (
    <div className="flex min-w-0 max-w-full flex-wrap items-center gap-x-3 gap-y-1 text-sm">
      <Link
        to={CATEGORIZE_PATH}
        onClick={onHub}
        className="shrink-0 text-ink-muted hover:text-ink hover:underline"
      >
        ← Hub
      </Link>
      {backToWindowLabel && onBackToWindow ? (
        <button
          type="button"
          className="shrink-0 text-ink-muted hover:text-ink hover:underline"
          onClick={onBackToWindow}
        >
          ← {backToWindowLabel}
        </button>
      ) : null}
      <span className="min-w-0 break-words font-medium text-ink">{title}</span>
      {honesty ? (
        <span className="min-w-0 max-w-full break-words text-ink-muted">{honesty}</span>
      ) : null}
    </div>
  );
}
