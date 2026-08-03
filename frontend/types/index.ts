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

export interface Upload {
  id: string;
  original_filename: string;
  entity_type: string;
  status: string;
  created_at: string;
}

export interface FieldCandidate {
  source_column: string;
  confidence: number;
  source: "alias" | "structural" | "ai";
  sample_values: string[];
}

export interface DetectMappingResponse {
  status: "reused" | "needs_confirmation";
  mapping_profile_id: string | null;
  suggested_mapping: Record<string, string | null>;
  columns: string[];
  field_candidates: Record<string, FieldCandidate[]>;
  unmapped_columns: string[];
}

export interface ConfirmMappingResponse {
  import_record_id: string;
  mapping_profile_id: string;
  status: string;
}
