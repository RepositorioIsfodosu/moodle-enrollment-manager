export interface Page<T> {
  items: T[];
  total: number;
  offset: number;
  limit: number;
}
export interface User {
  id: string;
  email: string;
  active: boolean;
  roles: string[];
  permissions?: string[];
  created_at: string;
}
export interface Settings {
  timezone: string;
  csv_max_bytes: number;
  csv_max_rows: number;
  csv_max_operations: number;
  enrollment_writes_enabled: boolean;
}
export interface Connection {
  id: string;
  name: string;
  base_url: string;
  description: string;
  active: boolean;
  status: string;
  token_configured: boolean;
  last_error_code: string | null;
  last_verified_at: string | null;
  configuration_version: number;
  latency_ms: number | null;
  available_functions: string[];
  missing_evaluated_functions: string[];
  site_metadata: Record<string, string | null>;
  limits: {
    requests_per_minute: number;
    max_concurrency: number;
    timeout_seconds: number;
    min_probe_interval_seconds: number;
    error_threshold: number;
    circuit_cooldown_seconds: number;
  };
}
export interface Destination {
  id: string;
  name: string;
  base_url: string;
  status: string;
  last_verified_at: string | null;
}
export interface CsvFile {
  id: string;
  original_name: string;
  row_count: number;
  byte_count: number;
  encoding: string;
  delimiter: string;
  headers: string[];
  preview: Record<string, string>[];
  created_at: string;
  sha256: string;
}
export interface Mapping {
  user_column: string | null;
  user_field: "username" | "email" | "idnumber";
  course_field: "id" | "shortname" | "idnumber";
  group_field: "id" | "name" | "idnumber";
  courses: { course: string; role: string | null; group: string | null }[];
  default_role_id: number | null;
  role_map: Record<string, number>;
  metadata_columns: Partial<Record<"period" | "campus", string>>;
}
export interface Import {
  id: string;
  file_id: string;
  original_name?: string;
  operation_count: number;
  counts: Record<string, number>;
  mapping_snapshot: Mapping;
  created_at?: string;
}
export interface Profile {
  id: string;
  name: string;
  mapping: Mapping;
  owner_id: string | null;
}
export interface Validation {
  id: string;
  connection_id: string;
  configuration_version: number;
  state: string;
  error_code: string | null;
  created_at: string;
  finished_at: string | null;
  total: number;
  checked: number;
  counts: Record<string, number>;
  progress_percent: number;
}
export interface Operation {
  retryable?: boolean;
  id: string;
  source_row: number;
  slot?: number;
  payload?: Record<string, unknown>;
  status?: string;
  state?: string;
  error_code: string | null;
  reason?: string;
  user_identifier?: string;
  course_identifier?: string;
  role_id?: number;
  retry_count?: number;
  reconciliation_count?: number;
  job_id?: string;
  job_name?: string;
}
export interface Batch {
  batch_size: number;
  pause_seconds: number;
  timeout_seconds: number;
  max_retries: number;
  retry_base_seconds: number;
  latency_threshold_ms: number;
  error_threshold: number;
  circuit_cooldown_seconds: number;
  allowed_hours_utc: number[];
  max_concurrency: 1;
}
export interface Job {
  id: string;
  name: string;
  connection_id: string;
  state: string;
  configuration: Batch & {
    validation_id: string;
    connection_version: number;
    execution_available: boolean;
  };
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  counts: Record<string, number>;
  total: number;
  progress_percent: number;
  runtime: {
    worker_seen_at?: string;
    last_latency_ms?: number;
    effective_pause_seconds?: number;
    last_error_code?: string;
  };
}
export interface Audit {
  id: string;
  created_at: string;
  action: string;
  actor_id: string | null;
  entity_id: string | null;
  safe_context: Record<string, unknown>;
}
export interface Attempt {
  id: string;
  record_id: string;
  number: number;
  outcome: string;
  error_code: string | null;
  created_at: string;
  context: Record<string, unknown>;
}
export interface Event {
  id: string;
  action: string;
  created_at: string;
  context: Record<string, unknown>;
}
export interface Approval {
  id: string;
  course_id: number;
  role_id: number;
  expires_at: string;
  reference: string;
  groups_authorized: boolean;
  full_enrollment_visibility: boolean;
  configuration_version: number;
  active: boolean;
}
