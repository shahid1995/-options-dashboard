import { C } from "@/lib/ui";

export default function SectionHeading({ tag, title, sub, style, level = 2 }) {
  const Tag = level === 1 ? "h1" : "h2";
  return (
    <div style={{ textAlign: "center", maxWidth: 640, margin: "0 auto 44px", ...style }}>
      {tag && (
        <div style={{ display: "inline-flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
          <span style={{ width: 26, height: 1, background: `linear-gradient(90deg, transparent, ${C.gold})` }} />
          <span style={{ fontSize: 11, letterSpacing: 2, color: C.gold, fontWeight: 700 }}>{tag}</span>
          <span style={{ width: 26, height: 1, background: `linear-gradient(90deg, ${C.gold}, transparent)` }} />
        </div>
      )}
      <Tag style={{ fontSize: 34, margin: "0 0 12px", letterSpacing: -0.5, fontWeight: 800, color: C.text, lineHeight: 1.2 }}>
        {title}
      </Tag>
      {sub && (
        <p style={{ color: C.muted, fontSize: 15, lineHeight: 1.7, margin: 0 }}>{sub}</p>
      )}
    </div>
  );
}
