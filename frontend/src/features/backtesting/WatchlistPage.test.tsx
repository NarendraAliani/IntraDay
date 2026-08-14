// frontend/src/features/backtesting/WatchlistPage.test.tsx
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { WatchlistPage } from "./WatchlistPage";
import { renderWithAuth } from "../../test/testAuth";

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("WatchlistPage", () => {
  it("lists existing watchlists and shows no order controls", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url.endsWith("/watchlists/")) {
          return jsonResponse([{ name: "core", instrument_ids: ["NSE:FIXTURE01"] }]);
        }
        return jsonResponse({ error_code: "not_found", message: "no route" }, 404);
      }),
    );
    renderWithAuth(<WatchlistPage />);
    await waitFor(() => expect(screen.getByText(/core/)).toBeInTheDocument());
    const bodyText = document.body.textContent ?? "";
    for (const forbidden of ["Buy", "Sell", "Place Order", "Quantity"]) {
      expect(bodyText).not.toContain(forbidden);
    }
  });

  it("saves a new watchlist", async () => {
    let saved = false;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url.endsWith("/watchlists/") && !saved) return jsonResponse([]);
        if (url.endsWith("/watchlists/save/")) {
          saved = true;
          return jsonResponse({ name: "new-list", instrument_ids: ["NSE:FIXTURE01"] }, 201);
        }
        if (url.endsWith("/watchlists/")) {
          return jsonResponse([{ name: "new-list", instrument_ids: ["NSE:FIXTURE01"] }]);
        }
        return jsonResponse({ error_code: "not_found", message: "no route" }, 404);
      }),
    );
    renderWithAuth(<WatchlistPage />);
    await waitFor(() => expect(screen.getByText(/No watchlists yet/)).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("Watchlist name"), { target: { value: "new-list" } });
    fireEvent.change(screen.getByLabelText(/Instruments/), { target: { value: "NSE:FIXTURE01" } });
    fireEvent.click(screen.getByRole("button", { name: "Save Watchlist" }));

    await waitFor(() => expect(screen.getByText(/new-list/)).toBeInTheDocument());
  });
});
