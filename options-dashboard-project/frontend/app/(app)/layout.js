"use client";
import Shell from "@/components/Shell";
import AuthGate from "@/components/AuthGate";

export default function AppLayout({ children }) {
  return (
    <AuthGate>
      <Shell>{children}</Shell>
    </AuthGate>
  );
}
