import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock the api module using vi.hoisted to avoid initialization order issues
const mockPost = vi.hoisted(() => vi.fn());

vi.mock("./api", () => ({
  api: { post: mockPost },
  resolveInlineLegs: (payload) => mockPost("/paper/resolve", payload).then((r) => r.data),
  resolveTemplateLegs: (id) => mockPost(`/paper/templates/${id}/resolve`).then((r) => r.data),
}));

import { resolveInlineLegs, resolveTemplateLegs } from "./api";

describe("resolveInlineLegs", () => {
  beforeEach(() => { mockPost.mockReset(); });

  it("calls POST /paper/resolve with correct payload", async () => {
    const payload = {
      symbol: "NIFTY",
      legs: [{ action: "buy", option_type: "call", strike: 25000, expiry: "2026-08-28", quantity: 1, lot_size: 65 }],
    };
    mockPost.mockResolvedValue({ data: { status: "RESOLVED", legs: [] } });
    const result = await resolveInlineLegs(payload);
    expect(mockPost).toHaveBeenCalledWith("/paper/resolve", payload);
    expect(result.status).toBe("RESOLVED");
  });

  it("returns the response data", async () => {
    const mockData = { status: "RESOLVED", symbol: "NIFTY", legs: [{ resolved_strike: 25000 }] };
    mockPost.mockResolvedValue({ data: mockData });
    const result = await resolveInlineLegs({ symbol: "NIFTY", legs: [] });
    expect(result).toEqual(mockData);
  });
});

describe("resolveTemplateLegs", () => {
  beforeEach(() => { mockPost.mockReset(); });

  it("calls POST /paper/templates/{id}/resolve", async () => {
    mockPost.mockResolvedValue({ data: { status: "RESOLVED", template_id: 42 } });
    const result = await resolveTemplateLegs(42);
    expect(mockPost).toHaveBeenCalledWith("/paper/templates/42/resolve");
    expect(result.template_id).toBe(42);
  });
});
