import PublicLayout from "@/components/public/PublicLayout";

export const metadata = {
  title: {
    default: "Options Dashboard — Options Trading & Analysis Platform",
    template: "%s | Options Dashboard",
  },
  description:
    "A professional options analysis and paper-trading platform for traders who want to turn market data into structured decisions.",
  openGraph: {
    type: "website",
    siteName: "Options Dashboard",
  },
};

export default function PublicGroupLayout({ children }) {
  return <PublicLayout>{children}</PublicLayout>;
}
