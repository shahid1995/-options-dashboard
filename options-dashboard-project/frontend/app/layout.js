export const metadata = {
  title: "Options Dashboard — Live Index Option Chains",
  description: "A real-time index options terminal for NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, NIFTYNXT50, SENSEX, BANKEX and SENSEX50 — live chains, max pain & PCR analytics, watchlist alerts, and paper trading. Powered by Upstox.",
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
