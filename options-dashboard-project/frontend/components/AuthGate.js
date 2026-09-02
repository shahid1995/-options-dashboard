"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getSessionId } from "@/lib/session";
import { getStatus } from "@/lib/api";

/**
 * Central auth guard for the (app) route group.
 *
 * On mount, checks whether a valid StrikeNova session exists.
 * If not, redirects to the public landing page (/).
 *
 * This prevents:
 * - Unauthenticated users from seeing protected page shells
 * - Stale "Not logged in" messages in the page body
 * - Protected data from being briefly rendered before auth check completes
 *
 * Note: broker-dependent failures (BROKER_AUTH_REQUIRED) do NOT trigger
 * this guard. Only a missing/invalid platform session causes redirect.
 */
export default function AuthGate({ children }) {
  const [checking, setChecking] = useState(true);
  const router = useRouter();

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        const session = getSessionId();
        if (!session) {
          if (!cancelled) router.replace("/");
          return;
        }
        const status = await getStatus();
        if (!cancelled) {
          if (!status.logged_in) {
            router.replace("/");
          } else {
            setChecking(false);
          }
        }
      } catch {
        if (!cancelled) router.replace("/");
      }
    })();

    return () => { cancelled = true; };
  }, [router]);

  if (checking) return null;

  return children;
}
