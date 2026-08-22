import { C } from "@/lib/ui";

export default function FeatureCard({ icon, title, desc, style }) {
  return (
    <div
      className="od-card"
      style={{
        background: C.surface,
        border: `1px solid ${C.border}`,
        borderRadius: 12,
        padding: "24px 22px",
        display: "flex",
        flexDirection: "column",
        gap: 10,
        ...style,
      }}
    >
      {icon && (
        <div
          style={{
            width: 42,
            height: 42,
            borderRadius: 10,
            background: "rgba(201,161,90,0.1)",
            border: "1px solid rgba(201,161,90,0.25)",
            display: "grid",
            placeItems: "center",
            fontSize: 18,
            color: C.gold,
            flexShrink: 0,
          }}
        >
          {icon}
        </div>
      )}
      <div style={{ fontSize: 15.5, fontWeight: 700, color: C.text }}>{title}</div>
      <div style={{ fontSize: 13, color: C.muted, lineHeight: 1.65 }}>{desc}</div>
    </div>
  );
}
