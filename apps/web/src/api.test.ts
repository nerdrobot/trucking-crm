import { describe, expect, it, vi, afterEach } from "vitest";
import { request, validPhone, initialLead, date, label } from "./api";
describe("API boundary", () => {
  afterEach(() => vi.unstubAllGlobals());
  it("sends a session key and reports server errors without pretending success", async () => {
    const fetcher = vi.fn().mockResolvedValue({
      ok: false,
      status: 403,
      json: async () => ({
        success: false,
        error: "Lead access denied",
        data: null,
      }),
    });
    vi.stubGlobal("fetch", fetcher);
    await expect(request("/leads", "secret")).rejects.toThrow(
      "Lead access denied",
    );
    expect(fetcher.mock.calls[0][1].headers.Authorization).toBe(
      "Bearer secret",
    );
  });
  it("serializes mutations and unwraps only successful responses", async () => {
    const fetcher = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, data: { id: "lead-1" } }),
    });
    vi.stubGlobal("fetch", fetcher);
    expect(await request("/leads", "key", "POST", { name: "Alex" })).toEqual({
      id: "lead-1",
    });
    expect(fetcher.mock.calls[0][1]).toMatchObject({
      method: "POST",
      body: '{"name":"Alex"}',
      headers: { "Content-Type": "application/json" },
    });
  });
  it("reports unavailable network", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
    );
    await expect(request("/leads", "key")).rejects.toThrow(
      "Cannot reach the service",
    );
  });
  it.each([
    [401, "invalid or expired"],
    [502, "Request failed (502)"],
  ])("handles non-JSON failures %s", async (status, message) => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status,
        json: async () => {
          throw Error();
        },
      }),
    );
    await expect(request("/me", "key")).rejects.toThrow(message);
  });
  it("rejects a failure envelope even on a 200 response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ success: false, error: "Permission denied" }),
      }),
    );
    await expect(request("/me", "key")).rejects.toThrow("Permission denied");
  });
  it("accepts only international phone numbers", () => {
    expect(validPhone("+13125550123")).toBe(true);
    expect(validPhone("3125550123")).toBe(false);
    expect(validPhone("+01234567890")).toBe(false);
  });
  it("defaults to no communications consent", () => {
    expect(initialLead.consent_sms).toBe(false);
    expect(initialLead.consent_voice).toBe(false);
  });
  it("formats absent dates and status labels", () => {
    expect(date()).toBe("Not scheduled");
    expect(date("2026-09-21T10:00:00Z")).toContain("2026");
    expect(label("opted_out")).toBe("opted out");
  });
});
