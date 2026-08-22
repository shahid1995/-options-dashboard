export const metadata = {
  title: {
    default: "Options Dashboard — Options Trading & Analysis Platform",
    template: "%s | Options Dashboard",
  },
  description:
    "A professional options analysis and paper-trading platform for Indian index options — live chains, strategy builder, paper & live execution modes, portfolio analytics, and risk controls.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body style={{ margin: 0, background: "#0B0E14", color: "#E7E9EE", fontFamily: "system-ui, sans-serif" }}>
        {children}
      </body>
    </html>
  );
}
