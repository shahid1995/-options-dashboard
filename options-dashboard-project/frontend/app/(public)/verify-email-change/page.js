import { Suspense } from "react";
import EmailTokenClient from "@/components/public/EmailTokenClient";

export const metadata = {
  title: "Confirm your new email — StrikeNova",
  robots: { index: false, follow: false },
};

export default function VerifyEmailChangePage() {
  return (
    <Suspense fallback={null}>
      <EmailTokenClient mode="email-change" />
    </Suspense>
  );
}
