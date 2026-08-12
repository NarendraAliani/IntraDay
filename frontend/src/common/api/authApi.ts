// frontend/src/common/api/authApi.ts
//
// Checkpoint 11: typed wrappers around the authentication API
// (/api/v1/auth/). Uses the same `apiGet`/`apiPost` client as every other
// resource - no separate HTTP abstraction for auth.
import { apiGet, apiPost } from "./client";
import type { components } from "@shared/generated_contracts/api-types";

export type CurrentUserResponse = components["schemas"]["CurrentUserResponse"];
export type LoginRequest = components["schemas"]["LoginRequest"];

/** Authenticates and starts a session. Throws `ApiRequestError` (401,
 * `error_code: "invalid_credentials"`) on failure - the same generic
 * message regardless of whether the username or the password was wrong. */
export function login(credentials: LoginRequest): Promise<CurrentUserResponse> {
  return apiPost<CurrentUserResponse>("/api/v1/auth/login/", credentials);
}

/** Ends the current session. Requires an existing authenticated session. */
export function logout(): Promise<CurrentUserResponse> {
  return apiPost<CurrentUserResponse>("/api/v1/auth/logout/");
}

/** Reports the current authentication state. Always resolves (never
 * throws for "not logged in" - the backend returns 200 with
 * `is_authenticated: false` for anonymous callers). Also the mechanism
 * that obtains the CSRF cookie before any state-changing request. */
export function fetchCurrentUser(): Promise<CurrentUserResponse> {
  return apiGet<CurrentUserResponse>("/api/v1/auth/session/");
}
