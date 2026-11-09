const GET_ENDPOINTS = new Set([
  "dashboard/summary",
  "dashboard/trends",
  "disputes",
  "invoices",
  "payouts",
  "activity",
  "copilot/insights",
  "events/stream",
]);

const QUERY_KEYS: Record<string, ReadonlySet<string>> = {
  "dashboard/trends": new Set(["days"]),
  disputes: new Set(["offset", "limit", "status", "search"]),
  invoices: new Set(["offset", "limit", "status", "search"]),
  payouts: new Set(["offset", "limit", "status", "search"]),
  activity: new Set(["offset", "limit"]),
};

export function isAllowedGetEndpoint(endpoint: string): boolean {
  return GET_ENDPOINTS.has(endpoint);
}

export function isAllowedPostEndpoint(endpoint: string): boolean {
  return endpoint === "copilot/ask";
}

export function areQueryParametersAllowed(
  endpoint: string,
  keys: Iterable<string>,
): boolean {
  const allowedKeys = QUERY_KEYS[endpoint] ?? new Set<string>();
  const seen = new Set<string>();
  for (const key of keys) {
    if (!allowedKeys.has(key) || seen.has(key)) {
      return false;
    }
    seen.add(key);
  }
  return true;
}
