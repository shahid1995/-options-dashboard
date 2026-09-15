import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";

const sourcePath = path.resolve(process.cwd(), "app/(public)/features/ClientPage.js");

describe("Features capability grid", () => {
  it("uses a two-column desktop layout so the four capability cards stay aligned", () => {
    const source = fs.readFileSync(sourcePath, "utf8");
    expect(source).toContain("<CardGrid minItemWidth={480} gap={SPACE.compLg}>");
  });
});
