import { C } from "@/lib/theme";

export default function ExpirySelect({ expiry, expiries, onChange }) {
  return (
    <select
      value={expiry ?? ""}
      onChange={(e) => onChange(e.target.value)}
      style={{ background: C.surface, color: C.text, border: `1px solid ${C.border}`, borderRadius: 6, padding: "6px 10px" }}
    >
      {expiries.map((exp) => (
        <option key={exp} value={exp}>
          {exp}
        </option>
      ))}
    </select>
  );
}
