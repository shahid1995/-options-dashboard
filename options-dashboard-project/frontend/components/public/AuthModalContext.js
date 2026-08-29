"use client";
import { createContext, useCallback, useContext, useState } from "react";
import { GoogleOAuthProvider } from "@react-oauth/google";
import AuthModal from "./AuthModal";

const AuthModalContext = createContext({ open: () => {} });

const GOOGLE_CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID || "";

export function useAuthModal() {
  return useContext(AuthModalContext);
}

export default function AuthModalProvider({ children }) {
  const [open, setOpen] = useState(false);

  const openModal = useCallback(() => setOpen(true), []);
  const closeModal = useCallback(() => setOpen(false), []);

  // If no Google Client ID is configured, render without GoogleOAuthProvider
  // (the Google button will still show but won't function — acceptable for local dev)
  const modal = <AuthModal open={open} onClose={closeModal} />;

  return (
    <AuthModalContext.Provider value={{ open: openModal }}>
      {children}
      {GOOGLE_CLIENT_ID ? (
        <GoogleOAuthProvider clientId={GOOGLE_CLIENT_ID}>
          {modal}
        </GoogleOAuthProvider>
      ) : (
        modal
      )}
    </AuthModalContext.Provider>
  );
}
