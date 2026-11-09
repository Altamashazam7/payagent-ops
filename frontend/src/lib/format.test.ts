import { describe, expect, it } from "vitest";

import { formatCurrency, formatDate } from "@/lib/format";

describe("formatCurrency", () => {
  it("preserves exact decimal digits for large monetary values", () => {
    expect(formatCurrency("9007199254740993.10", "USD")).toBe(
      "$9,007,199,254,740,993.10",
    );
  });

  it("respects currencies that have no minor units", () => {
    expect(formatCurrency("1250", "JPY")).toBe("¥1,250");
  });
});

describe("formatDate", () => {
  it("returns an explicit fallback for missing dates", () => {
    expect(formatDate(null)).toBe("—");
  });
});
