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
//
// Checkpoint 11: every request now sends `credentials: "include"` so the
// browser attaches the session cookie set by the backend (see
// docs/architecture/AUTHENTICATION_AUTHORIZATION.md) even though the Vite
// dev server and the Django dev server are different origins. POST
// requests attach the `X-CSRFToken` header read from the `csrftoken`
// cookie, matching Django's own documented AJAX/SPA CSRF pattern - the
// backend still enforces this server-side (see auth_views.py), this is
// only the client-side half of that contract.
import type { components } from "@shared/generated_contracts/api-types";

export type ApiError = components["schemas"]["ApiError"];

const DEFAULT_DEV_BASE_URL = "http://127.0.0.1:8000";
const CSRF_COOKIE_NAME = "csrftoken";
const CSRF_HEADER_NAME = "X-CSRFToken";

function resolveBaseUrl(): string {
  const configured = import.meta.env.VITE_API_BASE_URL;
  if (typeof configured === "string" && configured.length > 0) {
    return configured.replace(/\/$/, "");
  }
  return DEFAULT_DEV_BASE_URL;
}

/** Reads the CSRF token Django's `CsrfViewMiddleware` sets as a
 * (deliberately non-HttpOnly) cookie, so it can be echoed back as a
 * request header - the CSRF cookie itself is not a secret an attacker
 * could use alone (Django's protection relies on the *header* matching
 * the *cookie*, which a cross-site attacker cannot read or set). */
function readCsrfToken(): string | null {
  const match = document.cookie.match(new RegExp(`(?:^|; )${CSRF_COOKIE_NAME}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
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
  /** Dev-only (`DEBUG=True` on the backend, never in production/paper
   * settings) exception type/message/traceback some endpoints attach
   * for otherwise-hard-to-reproduce failures - NOT part of the typed
   * `ApiError` OpenAPI contract (that schema's own `details` field is
   * explicitly documented as "never a stack trace"), so read
   * defensively here rather than widening that contract. */
  readonly debugDetail?: { exception_type: string; exception_message: string; traceback: string };

  constructor(status: number, body: ApiError) {
    super(body.message);
    this.name = "ApiRequestError";
    this.status = status;
    this.errorCode = body.error_code;
    this.details = body.details;
    const rawDebugDetail = (body as { debug_detail?: unknown }).debug_detail;
    if (
      rawDebugDetail !== null &&
      typeof rawDebugDetail === "object" &&
      "exception_type" in rawDebugDetail
    ) {
      this.debugDetail = rawDebugDetail as ApiRequestError["debugDetail"];
    }
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

async function performRequest(
  url: string,
  method: "GET" | "POST" | "DELETE",
  body?: unknown,
): Promise<Response> {
  const headers: Record<string, string> = { Accept: "application/json" };
  let requestBody: string | undefined;
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    requestBody = JSON.stringify(body);
  }
  if (method === "POST" || method === "DELETE") {
    const csrfToken = readCsrfToken();
    if (csrfToken) {
      headers[CSRF_HEADER_NAME] = csrfToken;
    }
  }

  try {
    return await fetch(url, {
      method,
      headers,
      credentials: "include",
      body: requestBody,
    });
  } catch (cause) {
    throw new ApiNetworkError(cause);
  }
}

// Checkpoint 11: a single, optional hook the auth boundary can register to
// learn "the backend just told us this session is no longer valid"
// (a 401 from any endpoint, e.g. an expired/invalidated session cookie),
// without every individual API-consuming component needing its own 401
// handling. Deliberately narrow: no retry/refresh logic, no queuing of
// in-flight requests - just a single notification hook, registered once
// by AuthProvider (src/common/auth/AuthContext.tsx).
let onSessionExpired: (() => void) | null = null;

export function setSessionExpiredHandler(handler: (() => void) | null): void {
  onSessionExpired = handler;
}

async function decodeResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    if (response.status === 401) {
      onSessionExpired?.();
    }
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
 * Perform a POST request and decode the JSON body as `T`. `body` is
 * optional: activation endpoints send no request body (a bare
 * state-transition identified entirely by the URL path, matching the
 * backend's `request=None` `@extend_schema` declarations); the login
 * endpoint passes its credentials as `body`.
 */
export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const response = await performRequest(`${resolveBaseUrl()}${path}`, "POST", body);
  return decodeResponse<T>(response);
}

/**
 * Perform a DELETE request. Deliberately does not decode a JSON body -
 * delete endpoints return 204 No Content (see `watchlist_views.
 * delete_watchlist`) - but still routes a non-2xx response through the
 * same `ApiRequestError`/`ApiNetworkError` handling as every other verb.
 */
export async function apiDelete(path: string): Promise<void> {
  const response = await performRequest(`${resolveBaseUrl()}${path}`, "DELETE");
  if (!response.ok) {
    await decodeResponse(response);
  }
}
