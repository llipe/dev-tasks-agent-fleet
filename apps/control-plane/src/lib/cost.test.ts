/**
 * Unit tests for cost estimation — S-018 sub-tasks 18.5, 18.7, 18.10.
 *
 * Covers:
 * - estimateRunCost — complete (all models priced)
 * - estimateRunCost — partial (some models unpriced)
 * - estimateRunCost — fully unpriced
 * - Genuinely free run (usd=0, complete=true)
 * - Log warn on unpriced model_id
 * - Pricing table loader
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { estimateRunCost, loadPricingTable, type PricingTable } from "./cost.js";
import type { ModelUsage } from "../server/runs/span-to-run-mapper.js";

describe("estimateRunCost", () => {
  const pricingTable: PricingTable = {
    "us.anthropic.claude-sonnet-4-6": { inputPer1k: 0.003, outputPer1k: 0.015 },
    "us.anthropic.claude-haiku-3-5-20241022-v1:0": { inputPer1k: 0.0008, outputPer1k: 0.004 },
  };

  let warnSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  });

  afterEach(() => {
    warnSpy.mockRestore();
  });

  it("returns complete estimate when all models are priced", () => {
    const perModel: ModelUsage[] = [
      { modelId: "us.anthropic.claude-sonnet-4-6", tokensIn: 10_000, tokensOut: 5_000, calls: 3 },
    ];

    const result = estimateRunCost(perModel, pricingTable);

    // (10000/1000) * 0.003 + (5000/1000) * 0.015 = 0.03 + 0.075 = 0.105
    expect(result.usd).toBeCloseTo(0.105, 6);
    expect(result.complete).toBe(true);
    expect(result.unpricedModels).toEqual([]);
  });

  it("sums costs across multiple priced models", () => {
    const perModel: ModelUsage[] = [
      { modelId: "us.anthropic.claude-sonnet-4-6", tokensIn: 1000, tokensOut: 1000, calls: 1 },
      {
        modelId: "us.anthropic.claude-haiku-3-5-20241022-v1:0",
        tokensIn: 2000,
        tokensOut: 3000,
        calls: 2,
      },
    ];

    const result = estimateRunCost(perModel, pricingTable);

    // Sonnet: (1000/1000)*0.003 + (1000/1000)*0.015 = 0.003 + 0.015 = 0.018
    // Haiku: (2000/1000)*0.0008 + (3000/1000)*0.004 = 0.0016 + 0.012 = 0.0136
    // Total: 0.018 + 0.0136 = 0.0316
    expect(result.usd).toBeCloseTo(0.0316, 6);
    expect(result.complete).toBe(true);
    expect(result.unpricedModels).toEqual([]);
  });

  it("returns partial estimate when some models are unpriced", () => {
    const perModel: ModelUsage[] = [
      { modelId: "us.anthropic.claude-sonnet-4-6", tokensIn: 1000, tokensOut: 1000, calls: 1 },
      { modelId: "unknown-model-xyz", tokensIn: 5000, tokensOut: 2000, calls: 2 },
    ];

    const result = estimateRunCost(perModel, pricingTable);

    // Only sonnet is priced: (1000/1000)*0.003 + (1000/1000)*0.015 = 0.018
    expect(result.usd).toBeCloseTo(0.018, 6);
    expect(result.complete).toBe(false);
    expect(result.unpricedModels).toEqual(["unknown-model-xyz"]);
  });

  it("returns zero usd with complete=false when no models are priced", () => {
    const perModel: ModelUsage[] = [
      { modelId: "unknown-model-a", tokensIn: 1000, tokensOut: 500, calls: 1 },
      { modelId: "unknown-model-b", tokensIn: 2000, tokensOut: 1000, calls: 1 },
    ];

    const result = estimateRunCost(perModel, pricingTable);

    expect(result.usd).toBe(0);
    expect(result.complete).toBe(false);
    expect(result.unpricedModels).toEqual(["unknown-model-a", "unknown-model-b"]);
  });

  it("genuinely free run: all models priced, zero tokens → usd=0, complete=true", () => {
    const perModel: ModelUsage[] = [
      { modelId: "us.anthropic.claude-sonnet-4-6", tokensIn: 0, tokensOut: 0, calls: 1 },
    ];

    const result = estimateRunCost(perModel, pricingTable);

    expect(result.usd).toBe(0);
    expect(result.complete).toBe(true);
    expect(result.unpricedModels).toEqual([]);
  });

  it("handles empty perModel array (no model invocations) as free and complete", () => {
    const perModel: ModelUsage[] = [];

    const result = estimateRunCost(perModel, pricingTable);

    expect(result.usd).toBe(0);
    expect(result.complete).toBe(true);
    expect(result.unpricedModels).toEqual([]);
  });

  it("logs warn for each unpriced model_id", () => {
    const perModel: ModelUsage[] = [
      { modelId: "unknown-model-a", tokensIn: 100, tokensOut: 50, calls: 1 },
      { modelId: "unknown-model-b", tokensIn: 200, tokensOut: 100, calls: 1 },
    ];

    estimateRunCost(perModel, pricingTable);

    expect(warnSpy).toHaveBeenCalledTimes(2);
    expect(warnSpy).toHaveBeenCalledWith(expect.stringContaining("unknown-model-a"));
    expect(warnSpy).toHaveBeenCalledWith(expect.stringContaining("unknown-model-b"));
  });

  it("does not log warn when all models are priced", () => {
    const perModel: ModelUsage[] = [
      { modelId: "us.anthropic.claude-sonnet-4-6", tokensIn: 1000, tokensOut: 500, calls: 1 },
    ];

    estimateRunCost(perModel, pricingTable);

    expect(warnSpy).not.toHaveBeenCalled();
  });
});

describe("loadPricingTable", () => {
  it("returns a non-empty PricingTable object", () => {
    const table = loadPricingTable();

    expect(table).toBeDefined();
    expect(Object.keys(table).length).toBeGreaterThan(0);
  });

  it("every entry has inputPer1k and outputPer1k as numbers", () => {
    const table = loadPricingTable();

    for (const [, entry] of Object.entries(table)) {
      expect(typeof entry.inputPer1k).toBe("number");
      expect(typeof entry.outputPer1k).toBe("number");
      expect(entry.inputPer1k).toBeGreaterThanOrEqual(0);
      expect(entry.outputPer1k).toBeGreaterThanOrEqual(0);
    }
  });
});
