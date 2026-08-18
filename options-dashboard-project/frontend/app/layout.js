import Shell from "@/components/Shell";

export const metadata = {
  title: "Options Dashboard — Trading Terminal",
  description: "Professional options trading terminal for Indian index options — live chains, strategy builder, paper & live execution modes, portfolio analytics, and risk controls.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body style={{ margin: 0, background: "#0B0E14", color: "#E7E9EE", fontFamily: "system-ui, sans-serif" }}>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
