// frontend/src/common/components/Pagination.tsx
//
// Checkpoint FRONTEND-DATA-TABLES: a small, shared client-side
// pagination control - the SAME idiom `BacktestingWorkbenchPage.tsx`'s
// own `TradeTable` already established (filter -> slice a page ->
// Previous/Next + "Page X of Y"), extracted here so the instrument
// picker and the Compare page reuse one component instead of each
// re-inventing the pattern. Deliberately NOT a general-purpose table
// framework - just page state plus the two buttons, matching what both
// call sites actually need.
export interface PaginationProps {
  page: number;
  totalPages: number;
  onChange: (page: number) => void;
  /** Total item count across all pages, shown alongside Page X of Y so
   * the operator has a real sense of scale (e.g. "139 results"). */
  totalItems: number;
  itemLabel: string;
}

export function Pagination(props: PaginationProps): JSX.Element | null {
  if (props.totalPages <= 1) return null;
  const { page, totalPages, onChange, totalItems, itemLabel } = props;
  return (
    <div className="pagination-controls">
      <span className="pagination-controls__count">
        {totalItems} {itemLabel}
        {totalItems === 1 ? "" : "s"}
      </span>
      <button type="button" onClick={() => onChange(Math.max(1, page - 1))} disabled={page === 1}>
        ← Previous
      </button>
      <span>
        Page {page} of {totalPages}
      </span>
      <button
        type="button"
        onClick={() => onChange(Math.min(totalPages, page + 1))}
        disabled={page === totalPages}
      >
        Next →
      </button>
    </div>
  );
}

/** Shared page-slicing helper - keeps the "clamp page to totalPages,
 * compute the slice" arithmetic in one place rather than duplicated at
 * both call sites. */
export function paginate<T>(items: T[], page: number, pageSize: number): { pageItems: T[]; totalPages: number; currentPage: number } {
  const totalPages = Math.max(1, Math.ceil(items.length / pageSize));
  const currentPage = Math.min(Math.max(1, page), totalPages);
  const start = (currentPage - 1) * pageSize;
  return { pageItems: items.slice(start, start + pageSize), totalPages, currentPage };
}
