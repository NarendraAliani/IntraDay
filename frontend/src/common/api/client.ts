// frontend/src/common/api/client.ts
//
// Checkpoint 9: small, centralized API client. No heavy data-fetching
// framework (no react-query/SWR/axios) - a thin `fetch` wrapper is enough
// for a single read-only screen. Uses the generated OpenAPI contract types
// from @shared/generated_contracts/api-types (never hand-duplicated
// response shapes) and the backend's own `ApiErrorSerializer` contract
// (`components["schemas"]["ApiError"]`) for error handling - no competing
// frontend error schema is invented.
//
// Base URL comes from `VITE_API_BASE_URL` (see frontend/.env.example). A
// safe local-dev default is used when the variable is not set; this is not
// a secret and is always visible in the built JS bundle.
import type { components } from "@shared/generated_contracts/api-types";

export type ApiError = components["schemas"]["ApiError"];

const DEFAULT_DEV_BASE_URL = "http://127.0.0.1:8000";

function resolveBaseUrl(): string {
  const configured = import.meta.env.VITE_API_BASE_URL;
  if (typeof configured === "string" && configured.length > 0) {
    return configured.replace(/\/$/, "");
  }
  return DEFAULT_DEV_BASE_URL;
}

/**
 * Thrown when the backend responds with a non-2xx status and a body that
 * matches the `ApiError` contract (or, failing that, a best-effort
 * fallback that never leaks raw response text/HTML/stack traces).
 */
export class ApiRequestError extends Error {
  readonly status: number;
  readonly errorCode: string;
  readonly details?: Record<string, unknown>;

  constructor(status: number, body: ApiError) {
    super(body.message);
    this.name = "ApiRequestError";
    this.status = status;
    this.errorCode = body.error_code;
    this.details = body.details;
  }
}

/** Thrown when the network request itself fails (offline, DNS, CORS, etc.). */
export class ApiNetworkError extends Error {
  constructor(cause: unknown) {
    super("Unable to reach the IntraDay API. Check your network connection.");
    this.name = "ApiNetworkError";
    this.cause = cause;
  }
}

function isApiErrorShape(value: unknown): value is ApiError {
  return (
    typeof value === "object" &&
    value !== null &&
    "error_code" in value &&
    "message" in value &&
    typeof (value as Record<string, unknown>).error_code === "string" &&
    typeof (value as Record<string, unknown>).message === "string"
  );
}

async function performRequest(url: string, method: "GET" | "POST"): Promise<Response> {
  try {
    return await fetch(url, {
      method,
      headers: { Accept: "application/json" },
    });
  } catch (cause) {
    throw new ApiNetworkError(cause);
  }
}

async function decodeResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let parsed: unknown;
    try {
      parsed = await response.json();
    } catch {
      parsed = undefined;
    }
    if (isApiErrorShape(parsed)) {
      throw new ApiRequestError(response.status, parsed);
    }
    // Fallback: the backend did not return the documented ApiError
    // contract (e.g. an upstream proxy error page). Never surface raw
    // response text - it may contain HTML/server internals.
    throw new ApiRequestError(response.status, {
      error_code: "unknown_error",
      message: `Request failed with status ${response.status}.`,
    });
  }

  return (await response.json()) as T;
}

/**
 * Perform a GET request against the IntraDay API and decode the JSON body
 * as `T`. `T` should always be a `components["schemas"][...]` type from the
 * generated contract, never a hand-written interface, so the client stays
 * bound to the real OpenAPI shape.
 */
export async function apiGet<T>(path: string): Promise<T> {
  const response = await performRequest(`${resolveBaseUrl()}${path}`, "GET");
  return decodeResponse<T>(response);
}

/**
 * Perform a POST request with no request body (every current write
 * operation - activation - is a bare state-transition action identified
 * entirely by the URL path, matching the backend's `request=None`
 * `@extend_schema` declarations) and decode the JSON body as `T`.
 */
export async function apiPost<T>(path: string): Promise<T> {
  const response = await performRequest(`${resolveBaseUrl()}${path}`, "POST");
  return decodeResponse<T>(response);
}
