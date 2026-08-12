// frontend/src/common/useConfigQuery.ts
//
// Checkpoint 9: minimal fetch-on-mount/refetch-on-id-change hook shared by
// the three Configuration Viewer panels. Deliberately not a general data
// library (React Query/SWR) - a single-purpose hook is enough for one
// read-only screen with three near-identical panels (Objective #11: no
// heavy data-fetching framework).
import { useEffect, useState } from "react";

import { ApiNetworkError, ApiRequestError } from "./api/client";

export type QueryState<T> =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "success"; data: T };

export function useConfigQuery<T>(
  fetcher: (id: string) => Promise<T[]>,
  id: string,
): QueryState<T[]> {
  const [state, setState] = useState<QueryState<T[]>>({ status: "loading" });

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
        if (error instanceof ApiRequestError) {
          setState({ status: "error", message: error.message });
        } else if (error instanceof ApiNetworkError) {
          setState({ status: "error", message: error.message });
        } else {
          setState({ status: "error", message: "An unexpected error occurred." });
        }
      });

    return () => {
      cancelled = true;
    };
  }, [fetcher, id]);

  return state;
}
