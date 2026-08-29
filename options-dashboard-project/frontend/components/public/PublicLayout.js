"use client";
import { PUBLIC_CSS } from "./styles";
import PublicHeader from "./PublicHeader";
import PublicFooter from "./PublicFooter";
import AuthModalProvider from "./AuthModalContext";

export default function PublicLayout({ children }) {
  return (
    <AuthModalProvider>
      <div style={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
        <style>{PUBLIC_CSS}</style>
        <PublicHeader />
        <main style={{ flex: 1 }}>{children}</main>
        <PublicFooter />
      </div>
    </AuthModalProvider>
  );
}
