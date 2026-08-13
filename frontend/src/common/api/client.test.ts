// frontend/src/common/api/client.test.ts
//
// Checkpoint 9: API client tests. Mocks `global.fetch` (the network
// boundary) but exercises the real `apiGet` implementation end to end,
// including decoding a real `components["schemas"]["ApiError"]`-shaped
// error body.
import { afterEach, describe, expect, it, vi } from "vitest";

import { apiGet, apiPost, ApiNetworkError, ApiRequestError, setSessionExpiredHandler } from "./client";
import type { components } from "@shared/generated_contracts/api-types";

type RiskConfigurationResponse = components["schemas"]["RiskConfigurationResponse"];

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("apiGet", () => {
  it("decodes a successful JSON response as the requested contract type", async () => {
    const body: RiskConfigurationResponse = {
      risk_configuration_id: "default",
      version: "v1",
      limits: {
        max_intraday_loss: "10000.00",
        max_position_size: "50000.00",
        max_per_trade_risk: "1000.00",
      },
      created_at: "2026-08-12T10:00:00Z",
      is_active: true,
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await apiGet<RiskConfigurationResponse>("/api/v1/config/risk/default/");

    expect(result).toEqual(body);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/config/risk/default/"),
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("throws ApiRequestError carrying the backend's ApiError contract on a non-2xx response", async () => {
    const errorBody: components["schemas"]["ApiError"] = {
      error_code: "not_found",
      message: "No risk configuration versions found for 'missing'.",
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(errorBody), {
        status: 404,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(apiGet("/api/v1/config/risk/missing/")).rejects.toMatchObject({
      name: "ApiRequestError",
      status: 404,
      errorCode: "not_found",
      message: errorBody.message,
    });
  });

  it("falls back to a safe generic message when the error body does not match the ApiError contract", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response("<html>Internal Server Error</html>", {
        status: 500,
        headers: { "Content-Type": "text/html" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    try {
      await apiGet("/api/v1/config/risk/default/");
      expect.unreachable("apiGet should have thrown");
    } catch (error) {
      expect(error).toBeInstanceOf(ApiRequestError);
      const apiError = error as ApiRequestError;
      expect(apiError.status).toBe(500);
      // Never leaks the raw HTML body.
      expect(apiError.message).not.toContain("<html>");
    }
  });

  it("throws ApiNetworkError when fetch itself rejects", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("network down"));
    vi.stubGlobal("fetch", fetchMock);

    await expect(apiGet("/api/v1/config/risk/default/")).rejects.toBeInstanceOf(ApiNetworkError);
  });
});

// ---------------------------------------------------------------------------
// Checkpoint 17.2 (Defect 1): the authentication-vs-authorization status-
// code contract. A 401 means "you are not authenticated" (session
// expired/absent) - the ONLY case that should trigger the session-expiry
// handler and drop the user back to the login screen. A 403 means "you
// are authenticated but not permitted to do this" - it must NEVER be
// treated as a session-expiry event, or a legitimate permission denial
// would incorrectly log the user out.
// ---------------------------------------------------------------------------
describe("session-expiry vs. authorization-denial distinction", () => {
  afterEach(() => {
    setSessionExpiredHandler(null);
  });

  it("triggers the session-expiry handler on a 401 (authentication failure)", async () => {
    const handler = vi.fn();
    setSessionExpiredHandler(handler);
    const errorBody: components["schemas"]["ApiError"] = {
      error_code: "not_authenticated",
      message: "Authentication credentials were not provided.",
    };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(errorBody), {
          status: 401,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(apiGet("/api/v1/config/risk/default/")).rejects.toMatchObject({ status: 401 });

    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("does NOT trigger the session-expiry handler on a 403 (authorization failure)", async () => {
    const handler = vi.fn();
    setSessionExpiredHandler(handler);
    const errorBody: components["schemas"]["ApiError"] = {
      error_code: "forbidden",
      message: "You do not have permission to activate configuration.",
    };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(errorBody), {
          status: 403,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(apiPost("/api/v1/config/risk/default/v1/activate/")).rejects.toMatchObject({
      status: 403,
      errorCode: "forbidden",
    });

    // The critical assertion: a real permission denial must never be
    // mistaken for a session expiry - the handler must not fire.
    expect(handler).not.toHaveBeenCalled();
  });
});
