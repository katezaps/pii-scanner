/**
 * Shared API types — single source of truth for frontend/backend contract.
 *
 * Generated types come from openapi-typescript (run `npm run generate:types`).
 * SSE types are manual since they aren't in the OpenAPI schema.
 */

import type { components } from "./api-types";

// ── Generated from OpenAPI schema ───────────────────────────────

export type BrokerOut = components["schemas"]["BrokerOut"];
export type BrokersResponse = components["schemas"]["BrokersResponse"];
export type FetchResult = components["schemas"]["FetchResult"];
export type FetchSummary = components["schemas"]["FetchSummary"];
export type FetchResponse = components["schemas"]["FetchResponse"];
export type ScanListItem = components["schemas"]["ScanListItem"];
export type ScanListResponse = components["schemas"]["ScanListResponse"];
export type ScanState = components["schemas"]["ScanState"];
export type HealthResponse = components["schemas"]["HealthResponse"];
export type RunAuditAgentsRequest = components["schemas"]["RunAuditAgentsRequest"];
export type ConfirmOptOutUrl = components["schemas"]["ConfirmOptOutUrl"];

// ── SSE types (not in OpenAPI — /audit streams these via SSE) ───

export interface FormFieldMatch {
  identity_field: string;
  form_input: string;
  found: boolean | null;
}

export interface AgentResult {
  name: string;
  search_url: string;
  status_code: number | null;
  content_length: number | null;
  message: string | null;
  input_fields_found: string[];
  matched_inputs: FormFieldMatch[];
  opt_out_url: string | null;
}

export interface AcceptedField {
  field_type: string;
  status: string;
}

export interface PendingBroker {
  name: string;
  search_url: string;
}
