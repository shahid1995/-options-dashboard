"use client";
import { createContext, useCallback, useContext, useState } from "react";
import AuthModal from "./AuthModal";

const AuthModalContext = createContext({ open: () => {} });

export function useAuthModal() {
  return useContext(AuthModalContext);
}

export default function AuthModalProvider({ children }) {
  const [open, setOpen] = useState(false);

  const openModal = useCallback(() => setOpen(true), []);
  const closeModal = useCallback(() => setOpen(false), []);

  return (
    <AuthModalContext.Provider value={{ open: openModal }}>
      {children}
      <AuthModal open={open} onClose={closeModal} />
    </AuthModalContext.Provider>
  );
}
