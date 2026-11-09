import { describe, expect, it } from "vitest";

import {
  areQueryParametersAllowed,
  isAllowedGetEndpoint,
  isAllowedPostEndpoint,
} from "@/lib/proxy-policy";

describe("backend proxy allowlist", () => {
  it("allows only read-only workspaces and copilot questions", () => {
    expect(isAllowedGetEndpoint("payouts")).toBe(true);
    expect(isAllowedGetEndpoint("payouts/approve")).toBe(false);
    expect(isAllowedGetEndpoint("events/stream")).toBe(true);
    expect(isAllowedPostEndpoint("copilot/ask")).toBe(true);
    expect(isAllowedPostEndpoint("disputes/submit-evidence")).toBe(false);
  });

  it("rejects unrecognized query parameters before forwarding", () => {
    expect(
      areQueryParametersAllowed("disputes", ["status", "offset", "search"]),
    ).toBe(true);
    expect(
      areQueryParametersAllowed("disputes", ["status", "payee_email"]),
    ).toBe(false);
    expect(
      areQueryParametersAllowed("disputes", ["status", "status"]),
    ).toBe(false);
  });
});
