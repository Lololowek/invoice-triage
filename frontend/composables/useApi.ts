import type {
  DocumentOut, DocumentSummary, EditEntry, Metrics, ReviewOut, SchemaOut, Value,
} from '~/utils/types'

const api = $fetch.create({ baseURL: '/api' })

let schemaPromise: Promise<SchemaOut> | null = null

export function useApi() {
  return {
    // the schema never changes while the app runs: fetch it once
    schema: () => (schemaPromise ??= api<SchemaOut>('/schema')),
    listDocuments: () => api<DocumentSummary[]>('/documents'),
    getDocument: (id: string) => api<DocumentOut>(`/documents/${id}`),
    edits: (id: string) => api<EditEntry[]>(`/documents/${id}/edits`),
    metrics: () => api<Metrics>('/metrics'),
    upload(file: File) {
      const form = new FormData()
      form.append('file', file)
      return api<DocumentOut>('/documents', { method: 'POST', body: form })
    },
    review: (id: string, values: Record<string, Value>) =>
      api<ReviewOut>(`/documents/${id}/review`, { method: 'POST', body: { values } }),
  }
}

/** FastAPI puts the reason in `detail`: a string, or {fields: {path: message}} for a review. */
export function errorDetail(error: unknown): { message: string; fields: Record<string, string> } {
  const data = (error as { data?: { detail?: unknown } }).data
  const detail = data?.detail
  if (typeof detail === 'string') return { message: detail, fields: {} }
  if (detail && typeof detail === 'object' && 'fields' in detail) {
    return { message: 'Некоторые значения не приняты', fields: (detail as { fields: Record<string, string> }).fields }
  }
  const status = (error as { statusCode?: number }).statusCode
  if (status === 502 || status === 503 || status === 504 || status === undefined) {
    return { message: 'API не отвечает. Запущен ли `triage serve`?', fields: {} }
  }
  return { message: `Ошибка ${status}`, fields: {} }
}
