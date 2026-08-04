export interface Business {
  id: string;
  name: string;
  template: string;
  timezone: string;
  role: string;
}

export interface SubscriptionStatus {
  status: string | null;
  current_period_end: string | null;
}

export interface RejectionReason {
  count: number;
  message: string;
  sample_rows: Record<string, unknown>[];
}

export interface RejectionSummary {
  reasons?: Record<string, RejectionReason>;
  warnings?: Record<string, RejectionReason>;
}

export interface ImportRecordSummary {
  id: string;
  status: string;
  rows_total: number;
  rows_imported: number;
  rows_rejected: number;
  rejection_summary: RejectionSummary | null;
  reversed_at: string | null;
}

export interface Upload {
  id: string;
  original_filename: string;
  entity_type: string;
  status: string;
  created_at: string;
  import_record: ImportRecordSummary | null;
}

export interface ImportRunResponse {
  import_record_id: string;
  status: string;
  rows_total: number;
  rows_imported: number;
  rows_rejected: number;
  rejection_summary: RejectionSummary | null;
}

export interface ImportUndoResponse {
  import_record_id: string;
  status: string;
  reversed_at: string | null;
}

export interface FieldCandidate {
  source_column: string;
  confidence: number;
  source: "alias" | "structural" | "ai";
  sample_values: string[];
}

export interface DetectMappingResponse {
  status: "reused" | "needs_confirmation" | "header_not_found";
  mapping_profile_id: string | null;
  suggested_mapping: Record<string, string | null>;
  columns: string[];
  field_candidates: Record<string, FieldCandidate[]>;
  unmapped_columns: string[];
  preview_rows: string[][] | null;
}

export interface ConfirmMappingResponse {
  import_record_id: string;
  mapping_profile_id: string;
  status: string;
}
