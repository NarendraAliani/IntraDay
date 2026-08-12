// frontend/src/common/useConfigQuery.ts
//
// Checkpoint 9: minimal fetch-on-mount/refetch-on-id-change hook shared by
// the three Configuration Viewer panels. Deliberately not a general data
// library (React Query/SWR) - a single-purpose hook is enough for one
// read-only screen with three near-identical panels (Objective #11: no
// heavy data-fetching framework).
//
// Checkpoint 10: added an explicit `refetch()` so the activation workflow
// can re-pull real backend state after a successful activation instead of
// locally mutating `is_active` - the backend remains the sole source of
// truth for which version is active.
import { useCallback, useEffect, useState } from "react";

import { ApiNetworkError, ApiRequestError } from "./api/client";

export type QueryState<T> =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "success"; data: T };

export interface ConfigQueryResult<T> {
  state: QueryState<T[]>;
  /** Re-runs the fetch against the real backend and replaces `state` with the fresh result. */
  refetch: () => Promise<void>;
}

export function useConfigQuery<T>(
  fetcher: (id: string) => Promise<T[]>,
  id: string,
): ConfigQueryResult<T> {
  const [state, setState] = useState<QueryState<T[]>>({ status: "loading" });

  const load = useCallback(async (): Promise<void> => {
    try {
      const data = await fetcher(id);
      setState({ status: "success", data });
    } catch (error: unknown) {
      if (error instanceof ApiRequestError || error instanceof ApiNetworkError) {
        setState({ status: "error", message: error.message });
      } else {
        setState({ status: "error", message: "An unexpected error occurred." });
      }
    }
  }, [fetcher, id]);

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });

    fetcher(id)
      .then((data) => {
        if (!cancelled) {
          setState({ status: "success", data });
        }
      })
      .catch((error: unknown) => {
        if (cancelled) {
          return;
        }
        if (error instanceof ApiRequestError || error instanceof ApiNetworkError) {
          setState({ status: "error", message: error.message });
        } else {
          setState({ status: "error", message: "An unexpected error occurred." });
        }
      });

    return () => {
      cancelled = true;
    };
  }, [fetcher, id]);

  return { state, refetch: load };
}
