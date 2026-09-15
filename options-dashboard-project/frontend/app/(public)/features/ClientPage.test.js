import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";

const sourcePath = path.resolve(process.cwd(), "app/(public)/features/ClientPage.js");
const source = () => fs.readFileSync(sourcePath, "utf8");

describe("Features capability grid", () => {
  it("uses a two-column desktop layout so the four capability cards stay aligned", () => {
    expect(source()).toContain("<CardGrid minItemWidth={480} gap={SPACE.compLg}>");
  });
});

describe("Features product story", () => {
  it("composes the intelligence stack, deeper capabilities, product evidence and product principles", () => {
    const content = source();
    expect(content).toContain("<IntelligenceStack />");
    expect(content).toContain("<DeepCapabilityGrid />");
    expect(content).toContain("<ProductEvidenceGrid />");
    expect(content).toContain("<WhyStrikeNova />");
  });

  it("keeps the future roadmap explicitly separate from current product sections", () => {
    const content = source();
    expect(content).toContain("RESEARCH / FUTURE AREA");
    expect(content).toContain("FUTURE CAPABILITIES");
    expect(content).toContain("START YOUR WORKFLOW");
  });
});

describe("Features product evidence", () => {
  it("presents the six-step evidence sequence", () => {
    const content = source();
    expect(content).toContain("One workflow, six useful views");
    expect(content).toContain('title: "Market View"');
    expect(content).toContain('title: "Positioning"');
    expect(content).toContain('title: "Strategy"');
    expect(content).toContain('title: "Risk"');
    expect(content).toContain('title: "Rehearsal"');
    expect(content).toContain('title: "Review"');
  });
});
