import { Suspense } from "react";
import EmailTokenClient from "@/components/public/EmailTokenClient";

export const metadata = {
  title: "Verify your email — StrikeNova",
  robots: { index: false, follow: false },
};

export default function VerifyEmailPage() {
  return (
    <Suspense fallback={null}>
      <EmailTokenClient mode="verify" />
    </Suspense>
  );
}
