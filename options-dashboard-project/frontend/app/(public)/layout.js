import PublicLayout from "@/components/public/PublicLayout";

export const metadata = {
  title: {
    default: "StrikeNova — Options Intelligence for Structured Decisions",
    template: "%s | StrikeNova",
  },
  description:
    "StrikeNova is an options intelligence platform. Analyze market data, build strategies, paper trade, and review decisions in one structured workflow.",
  openGraph: {
    type: "website",
    siteName: "StrikeNova",
  },
};

export default function PublicGroupLayout({ children }) {
  return <PublicLayout>{children}</PublicLayout>;
}
