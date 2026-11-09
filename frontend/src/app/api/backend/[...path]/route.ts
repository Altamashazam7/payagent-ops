import { getToken } from "next-auth/jwt";
import { NextResponse, type NextRequest } from "next/server";

import { copilotQuestionSchema } from "@/lib/contracts";
import {
  areQueryParametersAllowed,
  isAllowedGetEndpoint,
  isAllowedPostEndpoint,
} from "@/lib/proxy-policy";

type RouteContext = { params: Promise<{ path: string[] }> };

function errorResponse(message: string, status: number): NextResponse {
  return NextResponse.json({ detail: message }, { status });
}

async function forward(
  request: NextRequest,
  endpoint: string,
  method: "GET" | "POST",
  body?: string,
  streaming = false,
): Promise<NextResponse> {
  const session = await getToken({
    req: request,
    secret: process.env.NEXTAUTH_SECRET,
  });
  const accessToken = session?.accessToken;
  if (
    !accessToken ||
    (session.accessTokenExpiresAt !== undefined &&
      session.accessTokenExpiresAt <= Math.floor(Date.now() / 1000))
  ) {
    return errorResponse("Authentication is required", 401);
  }

  const apiUrl = process.env.PAYAGENT_API_URL;
  if (!apiUrl) {
    return errorResponse("Commerce API is not configured", 503);
  }

  let baseUrl: URL;
  try {
    baseUrl = new URL(apiUrl);
  } catch {
    return errorResponse("Commerce API configuration is invalid", 503);
  }
  if (
    !["http:", "https:"].includes(baseUrl.protocol) ||
    baseUrl.username ||
    baseUrl.password ||
    baseUrl.pathname !== "/" ||
    baseUrl.search ||
    baseUrl.hash
  ) {
    return errorResponse("Commerce API configuration is invalid", 503);
  }
  if (
    process.env.NODE_ENV === "production" &&
    baseUrl.protocol !== "https:"
  ) {
    return errorResponse("Commerce API must use HTTPS", 503);
  }
  const target = new URL(`/api/v1/${endpoint}`, baseUrl);
  for (const [key, value] of request.nextUrl.searchParams) {
    target.searchParams.append(key, value);
  }

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method,
      headers: {
        authorization: `Bearer ${accessToken}`,
        ...(body ? { "content-type": "application/json" } : {}),
      },
      ...(body ? { body } : {}),
      cache: "no-store",
      signal: streaming ? request.signal : AbortSignal.timeout(12_000),
    });
  } catch (error) {
    if (error instanceof TypeError || error instanceof DOMException) {
      if (streaming && request.signal.aborted) {
        throw error;
      }
      return errorResponse("Commerce API is unavailable", 502);
    }
    throw error;
  }
  const headers = new Headers({
    "cache-control": "private, no-store",
    "content-type":
      upstream.headers.get("content-type") ?? "application/json; charset=utf-8",
  });
  const requestId = upstream.headers.get("x-request-id");
  if (requestId) {
    headers.set("x-request-id", requestId);
  }
  if (streaming) {
    headers.set("cache-control", "no-cache, no-transform");
    headers.set("x-accel-buffering", "no");
    return new NextResponse(upstream.body, {
      status: upstream.status,
      headers,
    });
  }
  return new NextResponse(await upstream.text(), {
    status: upstream.status,
    headers,
  });
}

export async function GET(
  request: NextRequest,
  context: RouteContext,
): Promise<NextResponse> {
  const { path } = await context.params;
  const endpoint = path.join("/");
  if (!isAllowedGetEndpoint(endpoint)) {
    return errorResponse("Reporting endpoint is not allowed", 404);
  }
  if (
    !areQueryParametersAllowed(
      endpoint,
      request.nextUrl.searchParams.keys(),
    )
  ) {
    return errorResponse("Query parameter is not allowed", 400);
  }
  return forward(request, endpoint, "GET", undefined, endpoint === "events/stream");
}

export async function POST(
  request: NextRequest,
  context: RouteContext,
): Promise<NextResponse> {
  const { path } = await context.params;
  if (!isAllowedPostEndpoint(path.join("/"))) {
    return errorResponse("Reporting endpoint is not allowed", 404);
  }
  let input: unknown;
  try {
    input = await request.json();
  } catch (error) {
    if (error instanceof SyntaxError) {
      return errorResponse("Request body must be valid JSON", 400);
    }
    throw error;
  }
  const parsed = copilotQuestionSchema.safeParse(input);
  if (!parsed.success) {
    return errorResponse("Question must be between 3 and 1000 characters", 422);
  }
  return forward(request, "copilot/ask", "POST", JSON.stringify(parsed.data));
}
