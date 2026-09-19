import { Suspense } from "react";
import EmailTokenClient from "@/components/public/EmailTokenClient";

export const metadata = {
  title: "Reset your password — StrikeNova",
  robots: { index: false, follow: false },
};

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={null}>
      <EmailTokenClient mode="reset" />
    </Suspense>
  );
}
