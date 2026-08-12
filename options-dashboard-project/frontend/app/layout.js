export const metadata = {
  title: "Options Dashboard",
  description: "NSE options dashboard",
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
