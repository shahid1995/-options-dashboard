import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";
import { COLOR, TYPE } from "./tokens";

function relativeLuminance(hex) {
  const rgb = hex.match(/[0-9a-f]{2}/gi).map((v) => parseInt(v, 16) / 255);
  const linear = rgb.map((v) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
}

function contrastRatio(foreground, background) {
  const a = relativeLuminance(foreground);
  const b = relativeLuminance(background);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

describe("Public typography and WCAG AA hardening", () => {
  it("uses an AA-safe faint text token on base and surface backgrounds", () => {
    expect(contrastRatio(COLOR.textFaint, COLOR.base)).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(COLOR.textFaint, COLOR.surface)).toBeGreaterThanOrEqual(4.5);
  });

  it("uses an AA-safe strong border for identifiable controls", () => {
    expect(contrastRatio(COLOR.borderStrong, COLOR.base)).toBeGreaterThanOrEqual(3);
    expect(contrastRatio(COLOR.borderStrong, COLOR.surface)).toBeGreaterThanOrEqual(3);
  });

  it("keeps the canonical typography scale intact", () => {
    expect(TYPE.h2.size).toBe("clamp(1.75rem, 3.5vw, 2.75rem)");
    expect(TYPE.body.size).toBe("1rem");
    expect(TYPE.label.size).toBe("0.8125rem");
  });

  it("CTA no longer uses the audited 26px/34px/15px typography exceptions", () => {
    const source = fs.readFileSync(path.resolve(process.cwd(), "components/public/CTASection.js"), "utf8");
    expect(source).not.toContain("fontSize: isMobile ? 26 : 34");
    expect(source).not.toContain("fontSize: 15");
    expect(source).toContain("fontSize: TYPE.h2.size");
    expect(source).toContain("fontSize: TYPE.body.size");
    expect(source).toContain("fontSize: TYPE.label.size");
  });

  it("root layout explicitly loads the canonical Inter and JetBrains Mono fonts", () => {
    const source = fs.readFileSync(path.resolve(process.cwd(), "app/layout.js"), "utf8");
    expect(source).toContain('from "next/font/google"');
    expect(source).toContain("Inter");
    expect(source).toContain("JetBrains_Mono");
  });
});
