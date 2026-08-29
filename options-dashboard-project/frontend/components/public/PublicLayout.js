"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { PUBLIC_CSS } from "./styles";
import PublicHeader from "./PublicHeader";
import PublicFooter from "./PublicFooter";
import AuthModalProvider from "./AuthModalContext";
import { captureGoogleIdTokenFromUrl } from "@/lib/session";
import { loginGoogle } from "@/lib/api";
import { setSessionId } from "@/lib/session";

/**
 * Handles Google OAuth redirect callback on public pages.
 * When Google redirects back with #id_token=..., this component
 * sends it to the backend and redirects to the dashboard.
 */
function GoogleRedirectHandler() {
  const router = useRouter();

  useEffect(() => {
    const result = captureGoogleIdTokenFromUrl();
    if (result) {
      const { idToken, redirectPath } = result;
      loginGoogle(idToken)
        .then((data) => {
          if (data?.session_id) {
            setSessionId(data.session_id);
          }
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
        <style>{PUBLIC_CSS}</style>
        <PublicHeader />
        <main style={{ flex: 1 }}>{children}</main>
        <PublicFooter />
      </div>
    </AuthModalProvider>
  );
}
