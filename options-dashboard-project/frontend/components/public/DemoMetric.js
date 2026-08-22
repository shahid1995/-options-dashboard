import { C } from "@/lib/ui";

export default function DemoMetric({ label, value, color, unit }) {
  return (
    <div style={{ textAlign: "center" }}>
      <div style={{ fontSize: 10, letterSpacing: 1.5, color: C.faint, marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 24, fontWeight: 800, color: color || C.gold, lineHeight: 1.1 }}>
        {value}
        {unit && <span style={{ fontSize: 13, fontWeight: 600, color: C.muted, marginLeft: 2 }}>{unit}</span>}
      </div>
    </div>
  );
}
