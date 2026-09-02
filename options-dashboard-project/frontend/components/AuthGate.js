"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getSessionId } from "@/lib/session";
import { getMe } from "@/lib/api";

/**
 * Central auth guard for the (app) route group.
 *
 * /auth/me is the authoritative platform-identity check. Broker connectivity
 * is deliberately not part of this decision: a logged-in user may have no
 * broker connected.
 *
 * Authentication failures redirect to the public landing page. Network or
 * server failures do not log the user out; they render a retryable state
 * because an outage is not evidence that the session is invalid.
 */
export default function AuthGate({ children }) {
  const [state, setState] = useState("checking");
  const [error, setError] = useState("");
  const [retryKey, setRetryKey] = useState(0);
  const router = useRouter();

  useEffect(() => {
    let cancelled = false;

    const verify = async () => {
      try {
        const session = getSessionId();
        if (!session) {
          if (!cancelled) router.replace("/");
          return;
        }

        await getMe();
        if (!cancelled) {
          setError("");
          setState("authenticated");
        }
      } catch (err) {
        if (cancelled) return;

        const status = err?.response?.status;
        if (status === 401 || status === 403) {
          router.replace("/");
          return;
        }

        setError("We couldn't verify your session. Check your connection and try again.");
        setState("error");
      }
    };

    verify();
    return () => {
      cancelled = true;
    };
  }, [router, retryKey]);

  if (state === "checking") return null;

  if (state === "error") {
    return (
      <div style={{ minHeight: "100vh", display: "grid", placeItems: "center", padding: 24 }}>
        <div style={{ textAlign: "center", maxWidth: 440 }}>
          <p style={{ fontSize: 14, marginBottom: 16 }}>{error}</p>
          <button type="button" onClick={() => setRetryKey((value) => value + 1)}>
            Retry
          </button>
        </div>
      </div>
    );
  }

  return children;
}
