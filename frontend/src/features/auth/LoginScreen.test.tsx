// frontend/src/features/auth/LoginScreen.test.tsx
//
// Checkpoint 11: login screen tests. `login` is a mocked function passed
// through a fixed `AuthContext.Provider` (see src/test/testAuth.tsx) -
// this isolates the *screen's* behavior (loading/disabled state, error
// rendering, form submission) from AuthProvider's own network logic,
// which AuthContext.test.tsx covers separately.
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ApiRequestError } from "../../common/api/client";
import { LoginScreen } from "./LoginScreen";
import { renderWithAuth } from "../../test/testAuth";

describe("LoginScreen", () => {
  it("has accessible, labeled username and password fields", () => {
    renderWithAuth(<LoginScreen />, {
      state: { status: "anonymous" },
    });

    expect(screen.getByLabelText("Username")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toHaveAttribute("type", "password");
  });

  it("disables the form and shows a loading label while authenticating", () => {
    renderWithAuth(<LoginScreen />, {
      state: { status: "anonymous" },
      isAuthenticating: true,
    });

    expect(screen.getByRole("button", { name: "Signing in…" })).toBeDisabled();
    expect(screen.getByLabelText("Username")).toBeDisabled();
  });

  it("shows a safe error message on invalid credentials without calling login again", async () => {
    const login = vi
      .fn()
      .mockRejectedValue(
        new ApiRequestError(401, {
          error_code: "invalid_credentials",
          message: "Invalid username or password.",
        }),
      );
    renderWithAuth(<LoginScreen />, { state: { status: "anonymous" }, login });

    fireEvent.change(screen.getByLabelText("Username"), { target: { value: "reader" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "wrong" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Invalid username or password."),
    );
    expect(login).toHaveBeenCalledTimes(1);
    expect(login).toHaveBeenCalledWith({ username: "reader", password: "wrong" });
  });

  it("submits the real generated LoginRequest shape to the login function on success", async () => {
    const login = vi.fn().mockResolvedValue(undefined);
    renderWithAuth(<LoginScreen />, { state: { status: "anonymous" }, login });

    fireEvent.change(screen.getByLabelText("Username"), { target: { value: "operator" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "correct" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() =>
      expect(login).toHaveBeenCalledWith({ username: "operator", password: "correct" }),
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
