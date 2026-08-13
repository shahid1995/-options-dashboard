import { C } from "@/lib/theme";

const LINKS = [
  { key: "chain", href: "/dashboard", label: "Option Chain" },
  { key: "paper", href: "/paper", label: "Paper Trading" },
];

export default function TopNav({ active }) {
  return (
    <div style={{ display: "flex", gap: 10, marginBottom: 16 }}>
      {LINKS.map((link) => {
        const isActive = active === link.key;
        return (
          <a
            key={link.key}
            href={link.href}
            style={{
              fontSize: 12.5,
              padding: "6px 14px",
              borderRadius: 6,
              border: `1px solid ${isActive ? C.gold : C.border}`,
              background: isActive ? "rgba(201,161,90,0.1)" : "transparent",
              color: isActive ? C.gold : C.muted,
              textDecoration: "none",
            }}
          >
            {link.label}
          </a>
        );
      })}
    </div>
  );
}
