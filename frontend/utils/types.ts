// Mirrors the Pydantic models in src/triage/result.py, review.py and api.py.

export type Value = string | boolean | null
export type Risk = 'high' | 'medium' | 'low'
export type Layer = 'schema' | 'grounding' | 'arithmetic'
export type FieldKind =
  | 'text' | 'date' | 'money' | 'number' | 'identifier' | 'currency' | 'derived'

export interface Flag {
  layer: Layer
  code: string
  message: string
}

export interface Source {
  via: 'candidate' | 'quote'
  candidate_id: string | null
  text: string
  start: number
  end: number
  match: 'exact' | 'fuzzy'
  score: number | null
}

export interface FieldResult {
  path: string
  spec: string
  kind: FieldKind
  value: Value
  source: Source | null
  flags: Flag[]
  risk: Risk
  needs_review: boolean
  review_reason: string
  status: 'ok' | 'flagged'
}

export interface DocumentOut {
  id: string
  filename: string
  uploaded_at: string
  reviewed_at: string | null
  mapper: string
  line_items_source: 'code' | 'model'
  fields: FieldResult[]
  document_flags: Flag[]
  final_values: Record<string, Value> | null
  text: string
}

export interface DocumentSummary {
  id: string
  filename: string
  uploaded_at: string
  reviewed_at: string | null
  mapper: string
  fields: number
  to_review: number
  flagged: number
}

export interface FieldSpec {
  name: string
  kind: FieldKind
  description: string
  required: boolean
  risk: Risk
}

export interface SchemaOut {
  fields: FieldSpec[]
  expense_categories: string[]
}

export type Action = 'corrected' | 'confirmed' | 'accepted'

export interface EditEntry {
  path: string
  extracted: Value
  final: Value
  action: Action
}

export interface ReviewOut {
  document_id: string
  reviewed_at: string
  corrected: string[]
  confirmed: number
  accepted: number
}

export interface CheckStats {
  fired: number
  corrected: number
  shown: number
}

export interface Metrics {
  documents: number
  fields: number
  shown: number
  review_load: number | null
  corrected: number
  corrected_in_queue: number
  caught_by_checks: number
  caught_by_policy: number
  false_alarms: number
  flag_precision: number | null
  corrected_outside_queue: number
  by_check: Record<string, CheckStats>
  by_field: Record<string, Record<string, number>>
}
