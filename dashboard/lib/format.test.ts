import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { friendlyWarning, formatMs, gateLabel } from "./format.ts";

describe("friendlyWarning", () => {
  it("does not treat 'not settled' as a missing Gemini key", () => {
    const msg = friendlyWarning(
      "settlement setl_MISS0000: not settled; no bank credit emitted"
    );
    assert.equal(
      msg,
      "Some payouts had not settled yet, so no bank credit was expected for them."
    );
  });

  it("still maps a missing Gemini key", () => {
    const msg = friendlyWarning("GEMINI_API_KEY is not set");
    assert.equal(
      msg,
      "No Gemini key loaded. Add GEMINI_API_KEY to the repo .env and restart the dashboard."
    );
  });

  it("maps a missing OpenRouter GLM key", () => {
    const msg = friendlyWarning("OPENROUTER_API_KEY is not set");
    assert.equal(
      msg,
      "No GLM key loaded. Add OPENROUTER_API_KEY (or ZAI_API_KEY) to the repo .env and restart the dashboard."
    );
  });

  it("maps a GLM time cap instead of a generic unavailable banner", () => {
    const msg = friendlyWarning("LLM budget of 90s exhausted; falling back to rules");
    assert.equal(
      msg,
      "GLM hit the time cap for this review. Rules finished the remaining leftovers."
    );
  });

  it("maps a GLM timeout", () => {
    const msg = friendlyWarning("GLM 5.2 timed out on a leftover. Rules finished the rest.");
    assert.equal(msg, "GLM 5.2 took too long on a leftover. Rules finished the rest.");
  });

  it("maps Razorpay adjustments without claiming Gemini failed", () => {
    const msg = friendlyWarning(
      "skipped Razorpay adjustment adj_Fc000000000058: not mapped to ledger/psp/bank"
    );
    assert.equal(
      msg,
      "Some rows were adjustments or transfers and were left out of the review."
    );
  });
});

describe("formatMs", () => {
  it("uses milliseconds under one second", () => {
    assert.equal(formatMs(420), "420 ms");
  });

  it("uses seconds at or above one second", () => {
    assert.equal(formatMs(1530), "1.53 s");
  });
});

describe("gateLabel", () => {
  it("maps boolean and null", () => {
    assert.equal(gateLabel(true), "Pass");
    assert.equal(gateLabel(false), "Fail");
    assert.equal(gateLabel(null), "n/a");
  });
});
