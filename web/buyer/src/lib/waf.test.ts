import { ensureWafToken, isWafChallenge } from "./waf";

describe("WAF challenge", () => {
  it("tells a WAF challenge apart from the API's own 202", () => {
    expect(isWafChallenge(new Response("<html>", { status: 202, headers: { "x-amzn-waf-action": "challenge" } }))).toBe(true);
    expect(isWafChallenge(new Response("{}", { status: 202 }))).toBe(false);
  });

  it("is a no-op without an SDK URL (local dev)", async () => {
    await expect(ensureWafToken()).resolves.toBeUndefined();
  });
});
