"use client";
import { PUBLIC_CSS } from "./styles";
import PublicHeader from "./PublicHeader";
import PublicFooter from "./PublicFooter";

export default function PublicLayout({ children }) {
  return (
    <div style={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      <style>{PUBLIC_CSS}</style>
      <PublicHeader />
      <main style={{ flex: 1 }}>{children}</main>
      <PublicFooter />
    </div>
  );
}
