export const metadata = {
  title: {
    default: "StrikeNova — Options Intelligence for Structured Decisions",
    template: "%s | StrikeNova",
  },
  description:
    "StrikeNova is an options intelligence platform. Analyze market data, build strategies, paper trade, and review decisions in one structured workflow.",
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
