import { Inter, JetBrains_Mono } from "next/font/google";
import { COLOR, TYPE } from "@/components/public/tokens";

const inter = Inter({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-inter",
});

const jetBrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-jetbrains-mono",
});

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
    <html lang="en" className={`${inter.variable} ${jetBrainsMono.variable}`}>
      <body
        style={{
          margin: 0,
          background: COLOR.baseElevated,
          color: COLOR.textPrimary,
          fontFamily: inter.style.fontFamily,
        }}
      >
        {children}
      </body>
    </html>
  );
}
