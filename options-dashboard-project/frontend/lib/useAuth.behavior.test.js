/**
 * Behavioral tests: transient /auth/me failures must NOT log the user out.
 *
 * Issue #61 contract:
 *   401 / 403            -> server explicitly rejected authentication -> clear user
 *   5xx / network error  -> session validity UNKNOWN -> preserve user, retryable error
 *
 * These tests drive the REAL useAuth hook through a minimal hoisted fake
 * React (useState/useEffect/useCallback are all the hook uses). State is
 * read through a probe with microtask flushing so actual async state
 * transitions are asserted — not mock wiring.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

// --- Hoisted fake React: replaces "react" BEFORE useAuth.js is imported ---
vi.mock("react", async (importOriginal) => {
  const actual = await importOriginal();
  const state = [];
  const effects = [];
  const fake = {
    ...actual,
    useState: (init) => {
      const i = state.length;
      state.push(init);
      const set = (v) => {
        state[i] = typeof v === "function" ? v(state[i]) : v;
      };
      return [state[i], set];
    },
    useEffect: (fn) => {
      effects.push(fn);
    },
    useCallback: (fn) => fn,
    // Probe: runs queued effects, then hands the live hook state to onState.
    __probe: ({ onState }) => {
      while (effects.length) effects.shift()();
      onState({ user: state[0], loading: state[1], error: state[2] });
      return null;
    },
    // Reset the fake's slot/effect queues between tests (they are module-
    // level and would otherwise leak state across tests).
    __reset: () => {
      state.length = 0;
      effects.length = 0;
    },
  };
  // Make the fake its own default export so `import React from "react"`
  // resolves to the fake.
  fake.default = fake;
  return fake;
});

vi.mock("./session", () => ({
  captureGoogleIdTokenFromUrl: vi.fn(() => null),
}));

vi.mock("./api", () => ({
  getMe: vi.fn(),
  logoutUser: vi.fn(),
  loginEmail: vi.fn(),
  registerEmail: vi.fn(),
  loginGoogle: vi.fn(),
  getAccountSession: vi.fn(),
  logoutAccount: vi.fn(),
}));

import { useAuth } from "./useAuth";
import * as api from "./api";

beforeEach(() => {
  vi.clearAllMocks();
});

let authRef = null;

/** Render the real hook once so its state slots and effects are registered. */
function mountHook() {
  React.__reset();
  authRef = null;
  function Probe() {
    authRef = useAuth();
    return null;
  }
  renderToStaticMarkup(React.createElement(Probe));
  if (!authRef) throw new Error("hook never mounted");
}

/**
 * Read the hook's live state (running any newly queued effects), then let
 * pending promise continuations settle before resolving. `isLoggedIn` is
 * derived exactly as the hook derives it (`!!user`).
 */
const readState = () =>
  new Promise((resolve) => {
    React.__probe({ onState: resolve });
  }).then((s) => new Promise((r) => setTimeout(() => r({ ...s, isLoggedIn: !!s.user }), 0)));

describe("useAuth checkAuth — transient failures must not log out (Issue #61)", () => {
  it("Case 1: existing user + /auth/me 500 -> user preserved, retryable error set", async () => {
    api.getMe.mockResolvedValueOnce({ user_id: "u1", email: "a@b.c" });
    mountHook();
    let s = await readState(); // runs mount effect (checkAuth)
    s = await readState(); // settled: user authenticated
    expect(s.user).toEqual({ user_id: "u1", email: "a@b.c" });
    expect(s.isLoggedIn).toBe(true);
    expect(s.error).toBeNull();

    // Next check: transient server failure.
    api.getMe.mockRejectedValueOnce({ response: { status: 500 }, message: "Internal Server Error" });
    await authRef.refresh();
    s = await readState();

    expect(s.user).toEqual({ user_id: "u1", email: "a@b.c" });
    expect(s.isLoggedIn).toBe(true);
    expect(s.error).toBe("Internal Server Error");
  });

  it("Case 2: existing user + network failure -> user preserved, retryable error set", async () => {
    api.getMe.mockResolvedValueOnce({ user_id: "u1" });
    mountHook();
    let s = await readState();
    s = await readState();
    expect(s.isLoggedIn).toBe(true);

    // Axios network errors carry no `response` at all.
    api.getMe.mockRejectedValueOnce(new Error("Network Error"));
    await authRef.refresh();
    s = await readState();

    expect(s.user).toEqual({ user_id: "u1" });
    expect(s.isLoggedIn).toBe(true);
    expect(s.error).toBe("Network Error");
  });

  it("Case 3: /auth/me 401 -> user cleared", async () => {
    api.getMe.mockResolvedValueOnce({ user_id: "u1" });
    mountHook();
    let s = await readState();
    s = await readState();
    expect(s.isLoggedIn).toBe(true);

    api.getMe.mockRejectedValueOnce({ response: { status: 401 } });
    await authRef.refresh();
    s = await readState();

    expect(s.user).toBeNull();
    expect(s.isLoggedIn).toBe(false);
  });

  it("Case 4: /auth/me 403 -> user cleared", async () => {
    api.getMe.mockResolvedValueOnce({ user_id: "u1" });
    mountHook();
    let s = await readState();
    s = await readState();
    expect(s.isLoggedIn).toBe(true);

    api.getMe.mockRejectedValueOnce({ response: { status: 403 } });
    await authRef.refresh();
    s = await readState();

    expect(s.user).toBeNull();
    expect(s.isLoggedIn).toBe(false);
  });

  it("recovery: successful /auth/me after a transient failure updates the authoritative user and clears the error", async () => {
    api.getMe.mockRejectedValueOnce({ response: { status: 503 }, message: "Service Unavailable" });
    mountHook();
    let s = await readState();
    s = await readState();
    expect(s.user).toBeNull(); // never authenticated in this scenario
    expect(s.error).toBe("Service Unavailable"); // retryable, not a logout

    api.getMe.mockResolvedValueOnce({ user_id: "u2" });
    await authRef.refresh();
    s = await readState();

    expect(s.user).toEqual({ user_id: "u2" });
    expect(s.isLoggedIn).toBe(true);
    expect(s.error).toBeNull();
  });

  it("recovery while authenticated: 502 then success keeps the session authenticated throughout", async () => {
    api.getMe.mockResolvedValueOnce({ user_id: "u1" });
    mountHook();
    let s = await readState();
    s = await readState();
    expect(s.isLoggedIn).toBe(true);

    api.getMe.mockRejectedValueOnce({ response: { status: 502 }, message: "Bad Gateway" });
    await authRef.refresh();
    s = await readState();
    expect(s.isLoggedIn).toBe(true);
    expect(s.error).toBe("Bad Gateway");

    api.getMe.mockResolvedValueOnce({ user_id: "u1", email: "a@b.c" });
    await authRef.refresh();
    s = await readState();
    expect(s.user).toEqual({ user_id: "u1", email: "a@b.c" });
    expect(s.isLoggedIn).toBe(true);
    expect(s.error).toBeNull();
  });

  it("checkAccountSession: transient 5xx preserves an authenticated user; 401 clears it", async () => {
    api.getMe.mockResolvedValueOnce({ user_id: "u1" });
    mountHook();
    let s = await readState();
    s = await readState();
    expect(s.isLoggedIn).toBe(true);

    // Transient failure on the account-session check: user must survive.
    api.getAccountSession.mockRejectedValueOnce({ response: { status: 502 }, message: "Bad Gateway" });
    await authRef.checkAccountSession();
    s = await readState();
    expect(s.user).toEqual({ user_id: "u1" });
    expect(s.isLoggedIn).toBe(true);
    expect(s.error).toBe("Bad Gateway");

    // Explicit rejection: authenticated state must clear.
    api.getAccountSession.mockRejectedValueOnce({ response: { status: 401 } });
    await authRef.checkAccountSession();
    s = await readState();
    expect(s.user).toBeNull();
    expect(s.isLoggedIn).toBe(false);
  });
});
