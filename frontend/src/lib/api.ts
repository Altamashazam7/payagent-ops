import type { z } from "zod";

export const backendEndpoints = [
  "dashboard/summary",
  "dashboard/trends",
  "disputes",
  "invoices",
  "payouts",
  "activity",
  "copilot/insights",
  "copilot/ask",
] as const;

export type BackendEndpoint = (typeof backendEndpoints)[number];

export async function readBackend<T>(
  endpoint: BackendEndpoint,
  schema: z.ZodType<T>,
  query?: URLSearchParams,
): Promise<T> {
  const suffix = query?.size ? `?${query.toString()}` : "";
  const response = await fetch(`/api/backend/${endpoint}${suffix}`, {
    cache: "no-store",
  });
  return parseResponse(response, schema);
}

export async function askBackend<T>(
  endpoint: "copilot/ask",
  body: unknown,
  schema: z.ZodType<T>,
): Promise<T> {
  const response = await fetch(`/api/backend/${endpoint}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  return parseResponse(response, schema);
}

async function parseResponse<T>(
  response: Response,
  schema: z.ZodType<T>,
): Promise<T> {
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    const detail =
      typeof body === "object" &&
      body !== null &&
      "detail" in body &&
      typeof body.detail === "string"
        ? body.detail
        : `Reporting API request failed (${response.status})`;
    throw new Error(detail);
  }
  const payload: unknown = await response.json();
  return schema.parse(payload);
}
