// Typed API client. The frontend MUST NEVER call Razorpay directly
// (CLAUDE.md section 43). Every endpoint here is the existing backend surface.
//
// Each function:
//   - returns a typed response,
//   - throws `ApiError` (or one of the more specific subclasses) on failure,
//   - never silently swallows HTTP errors.

import type {
  AnalyticsOverview,
  ApprovalResponse,
  AuditEventOut,
  CaseDetail,
  CaseSummary,
  ExecutionResponse,
  TransactionSummary,
} from "./types";

const BASE: string =
  (import.meta.env.VITE_API_BASE as string | undefined) ??
  "http://localhost:8000";

// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------
export class ApiError extends Error {
  readonly status: number;
  readonly detail: string | null;
  readonly body: unknown;

  constructor(
    message: string,
    options: { status: number; body: unknown; detail: string | null },
  ) {
    super(message);
    this.name = "ApiError";
    this.status = options.status;
    this.body = options.body;
    this.detail = options.detail;
  }
}

export class NotFoundError extends ApiError {
  constructor(detail: string | null) {
    super(detail ?? "not found", { status: 404, body: null, detail });
    this.name = "NotFoundError";
  }
}

export class StateConflictError extends ApiError {
  constructor(detail: string | null) {
    super(detail ?? "conflict", { status: 409, body: null, detail });
    this.name = "StateConflictError";
  }
}

export class UnauthorizedError extends ApiError {
  constructor(detail: string | null) {
    super(detail ?? "unauthorized", { status: 401, body: null, detail });
    this.name = "UnauthorizedError";
  }
}

// ---------------------------------------------------------------------------
// Core fetch wrapper
// ---------------------------------------------------------------------------
interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
}

async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const init: RequestInit = {
    method: opts.method ?? "GET",
    headers: { Accept: "application/json" },
  };
  if (opts.signal) {
    init.signal = opts.signal;
  }
  if (opts.body !== undefined) {
    init.headers = {
      ...(init.headers as Record<string, string>),
      "Content-Type": "application/json",
    };
    init.body = JSON.stringify(opts.body);
  }

  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, init);
  } catch (err) {
    const reason = err instanceof Error ? err.message : String(err);
    throw new ApiError(`Network error contacting backend: ${reason}`, {
      status: 0,
      body: null,
      detail: null,
    });
  }

  if (res.status === 204) {
    return undefined as T;
  }

  let body: unknown = null;
  const contentType = res.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    try {
      body = await res.json();
    } catch {
      body = null;
    }
  } else {
    try {
      body = await res.text();
    } catch {
      body = null;
    }
  }

  if (!res.ok) {
    const detail =
      typeof body === "object" && body !== null && "detail" in body
        ? ((body as { detail: unknown }).detail as string | null)
        : null;
    const message =
      typeof detail === "string"
        ? detail
        : `Request failed with status ${res.status}`;
    if (res.status === 404) throw new NotFoundError(detail);
    if (res.status === 409) throw new StateConflictError(detail);
    if (res.status === 401) throw new UnauthorizedError(detail);
    throw new ApiError(message, { status: res.status, body, detail });
  }

  return body as T;
}

function qs(params: Record<string, unknown>): string {
  const parts: string[] = [];
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    parts.push(`${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`);
  }
  return parts.length === 0 ? "" : `?${parts.join("&")}`;
}

// ---------------------------------------------------------------------------
// Typed wrappers
// ---------------------------------------------------------------------------
export function getAnalytics(): Promise<AnalyticsOverview> {
  return request<AnalyticsOverview>("/api/analytics/overview");
}

export interface ListCasesParams {
  [key: string]: string | number | undefined;
  status?: string;
  action?: string;
  limit?: number;
  offset?: number;
}

export function listRecoveryCases(
  params: ListCasesParams = {},
): Promise<CaseSummary[]> {
  return request<CaseSummary[]>(`/api/recovery/cases${qs(params)}`);
}

export function getRecoveryCase(caseId: string): Promise<CaseDetail> {
  return request<CaseDetail>(`/api/recovery/cases/${encodeURIComponent(caseId)}`);
}

export function approveRecovery(caseId: string): Promise<ApprovalResponse> {
  return request<ApprovalResponse>(
    `/api/recovery/cases/${encodeURIComponent(caseId)}/approve`,
    { method: "POST" },
  );
}

export function executeRecovery(caseId: string): Promise<ExecutionResponse> {
  return request<ExecutionResponse>(
    `/api/recovery/cases/${encodeURIComponent(caseId)}/execute`,
    { method: "POST" },
  );
}

export function getAudit(caseId: string): Promise<AuditEventOut[]> {
  return request<AuditEventOut[]>(`/api/audit/${encodeURIComponent(caseId)}`);
}

export interface ListTransactionsParams {
  [key: string]: string | number | undefined;
  status?: string;
  limit?: number;
  offset?: number;
}

export function listTransactions(
  params: ListTransactionsParams = {},
): Promise<TransactionSummary[]> {
  return request<TransactionSummary[]>(`/api/transactions${qs(params)}`);
}

export { BASE as API_BASE };
