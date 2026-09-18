"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { PUBLIC_CSS } from "./styles";
import { PUBLIC_DS_CSS } from "./motion";
import PublicHeader from "./PublicHeader";
import PublicFooter from "./PublicFooter";
import AuthModalProvider from "./AuthModalContext";
import { captureGoogleIdTokenFromUrl } from "@/lib/session";
import { loginGoogle } from "@/lib/api";

/**
 * Handles Google OAuth redirect callback on public pages.
 * When Google redirects back with #id_token=..., this component
 * sends it to the backend and redirects to the authenticated app.
 */
function GoogleRedirectHandler() {
  const router = useRouter();

  useEffect(() => {
    const result = captureGoogleIdTokenFromUrl();
    if (result) {
      const { idToken, redirectPath, state } = result;
      loginGoogle(idToken, state)
        .then(() => {
          // The platform session travels ONLY via the HttpOnly
          // strikenova_session cookie set by the backend (Issue #61).
          // Never place session credentials in URL fragments — the
          // retired cross-origin session fragment handoff is removed.
          router.push(redirectPath || "/dashboard");
        })
        .catch((err) => {
          console.error("Google login failed:", err);
          // Stay on the page — user can try again
        });
    }
  }, [router]);

  return null;
}

export default function PublicLayout({ children }) {
  return (
    <AuthModalProvider>
      <GoogleRedirectHandler />
      <div style={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
        <style dangerouslySetInnerHTML={{ __html: PUBLIC_CSS }} />
        <style dangerouslySetInnerHTML={{ __html: PUBLIC_DS_CSS }} />
        <PublicHeader />
        <main style={{ flex: 1 }}>{children}</main>
        <PublicFooter />
      </div>
    </AuthModalProvider>
  );
}
