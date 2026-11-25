import request from './request'

export interface KnowledgeUploadPolicy {
  allowed_extensions?: string[]
  max_file_size_mb?: number
  max_upload_files?: number
}

interface KnowledgeSearchStatus {
  active_edition?: string | null
  search_provider?: string | null
  search_available?: boolean
  search_fallback?: boolean
  search_fallback_reason?: 'workspace_mismatch' | 'provider_unavailable' | null
  original_quote_status?: { state: 'ready' | 'unmounted' | 'index_needed'; scan_available: boolean } | null
}

export interface KnowledgeHealth extends KnowledgeSearchStatus {
  available: boolean
  provider?: string
  workspace_slug?: string
  document_count?: number
  upload_policy?: KnowledgeUploadPolicy
  error?: string
  [key: string]: unknown
}

export interface KnowledgeDocument {
  id: string
  filename: string
  size?: number
  status?: string
  created_at?: string
  title?: string
  book?: string
  book_title?: string
  doc_id?: string
  seq?: string
  source_pdf?: string
  source_path?: string
  modified_at?: string
  version?: string
  readable?: boolean
  source_status?: string
  message?: string
  section_count?: number
  page?: number | null
  page_start?: number
  page_end?: number
  edition?: string
  bundled?: boolean
  catalog_kind?: 'chapter' | 'subsection'
  reading_kind?: 'body' | 'guide' | 'excerpt' | null
  metadata?: Record<string, string | null>
}

export interface KnowledgeCatalog extends KnowledgeSearchStatus {
  documents: KnowledgeDocument[]
  provider: string
  count: number
  readable_count: number
  catalog_version: string
  checked_at: string
}

export interface KnowledgeFullDocument extends KnowledgeDocument {
  content: string
  sections: { id: string; line: number; level: number; title: string }[]
  edition_version?: string
  scope: 'current_document'
  truncated: boolean
  source_kind: string
  historical_edition?: boolean
  warnings?: string[]
  reviewed_notes?: KnowledgeReviewNote[]
  original_pages?: KnowledgeOriginalPage[]
  subsections?: KnowledgeDocument[]
}

export interface KnowledgeOriginalPage {
  physical: number
  section_id?: string | null
  preview: boolean
  printed_hint?: string
  original_status?: string
}

export interface KnowledgeReviewNote {
  id: string
  title: string
  content: string
  reference: string
  url: string
}

export const getKnowledgeCatalog = () =>
  request.get<KnowledgeCatalog, KnowledgeCatalog>('/ai/knowledge/catalog', { silent: true })

export const readKnowledgeDocument = (params: { document_id?: string; filename?: string; version?: string }) =>
  request.get<KnowledgeFullDocument, KnowledgeFullDocument>('/ai/knowledge/read', { params, silent: true })

export const getKnowledgeOriginalFigure = (params: { document_id: string; version: string; page: number }) =>
  request.get<Blob, Blob>('/ai/knowledge/original-figure', { params, responseType: 'blob', silent: true })

export interface KnowledgeSearchResult {
  score?: number | null
  text?: string
  content?: string
  title?: string
  filename?: string
  book_title?: string
  edition?: string
  document_id?: string
  document_version?: string | null
  edition_version?: string | null
  section_id?: string | null
  page?: number | null
  partial_readonly_table?: boolean
  reviewed_notes?: KnowledgeReviewNote[]
  [key: string]: unknown
}

export const getKnowledgeDocuments = () =>
  request.get<KnowledgeDocument[], KnowledgeDocument[]>('/ai/knowledge/documents')

export const getKnowledgeHealth = () =>
  request.get<KnowledgeHealth, KnowledgeHealth>('/ai/knowledge/health')

export const deleteKnowledgeDocument = (docId: string) =>
  request.delete(`/ai/knowledge/documents/${encodeURIComponent(docId)}`)

export const searchKnowledge = (data: { question: string; top_k?: number }) =>
  request.post<KnowledgeSearchResult[], KnowledgeSearchResult[]>('/ai/knowledge/search', data)

export interface OriginalQuoteResult {
  title: string
  document_id: string
  document_version: string
  book_title: string
  edition: string
  page: number
  match_type?: 'scan_locator'
}

interface OriginalQuoteResponse {
  edition: string
  results: OriginalQuoteResult[]
}

export const searchOriginalQuote = (data: { quote: string; book?: number }) =>
  request.post<OriginalQuoteResponse, OriginalQuoteResponse>('/ai/knowledge/original-quote', data, { silent: true })
