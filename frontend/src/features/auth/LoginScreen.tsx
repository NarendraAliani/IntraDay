// frontend/src/features/auth/LoginScreen.tsx
//
// Checkpoint 11: minimal real login screen. Security infrastructure, not
// visual branding - a username field, a password field, a submit button,
// and the three states (idle/loading/error) the workflow needs.
import { useId, useState } from "react";

import { ApiNetworkError, ApiRequestError } from "../../common/api/client";
import { useAuth } from "../../common/auth/AuthContext";

function describeLoginError(error: unknown): string {
  if (error instanceof ApiRequestError) {
    // A 403 with the generic "unknown_error" code on the login endpoint
    // specifically means Django's CSRF check rejected the request
    // before credentials were ever checked (almost always: no
    // `csrftoken` cookie was present yet, because the app loaded before
    // the backend was reachable, or a stale tab was left open across a
    // backend restart) - a real login failure (wrong password) instead
    // returns a proper 401 with a specific message. Distinguishing the
    // two here means an operator sees an actionable instruction instead
    // of a bare status code, without changing any authentication or
    // CSRF behavior itself.
    if (error.status === 403 && error.errorCode === "unknown_error") {
      return "Your session isn't ready yet. Please reload this page and try signing in again.";
    }
    return error.message;
  }
  if (error instanceof ApiNetworkError) {
    return error.message;
  }
  return "An unexpected error occurred.";
}

export function LoginScreen(): JSX.Element {
  const { login, isAuthenticating } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const usernameId = useId();
  const passwordId = useId();
  const errorId = useId();

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setError(null);
    try {
      // Password is never logged, never persisted (not even in this
      // component's state after submission), and never sent anywhere
      // except this one request body over the login endpoint.
      await login({ username, password });
    } catch (submitError) {
      setError(describeLoginError(submitError));
    }
  }

  return (
    <main className="login-screen">
      <form className="login-form" onSubmit={(event) => void handleSubmit(event)}>
        <h1>IntraDay</h1>
        <p className="login-form__subtitle">Sign in to the control plane.</p>

        <div className="login-form__field">
          <label htmlFor={usernameId}>Username</label>
          <input
            id={usernameId}
            name="username"
            type="text"
            autoComplete="username"
            required
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            disabled={isAuthenticating}
          />
        </div>

        <div className="login-form__field">
          <label htmlFor={passwordId}>Password</label>
          <input
            id={passwordId}
            name="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            disabled={isAuthenticating}
            aria-describedby={error ? errorId : undefined}
          />
        </div>

        {error && (
          <p id={errorId} role="alert" className="login-form__error">
            {error}
          </p>
        )}

        <button type="submit" disabled={isAuthenticating}>
          {isAuthenticating ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </main>
  );
}
