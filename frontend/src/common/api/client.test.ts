// frontend/src/common/api/client.test.ts
//
// Checkpoint 9: API client tests. Mocks `global.fetch` (the network
// boundary) but exercises the real `apiGet` implementation end to end,
// including decoding a real `components["schemas"]["ApiError"]`-shaped
// error body.
import { afterEach, describe, expect, it, vi } from "vitest";

import { apiGet, ApiNetworkError, ApiRequestError } from "./client";
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
