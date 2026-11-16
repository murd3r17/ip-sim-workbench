import request from './request'

export interface KnowledgeUploadPolicy {
  allowed_extensions?: string[]
  max_file_size_mb?: number
  max_upload_files?: number
}

export interface KnowledgeHealth {
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
  metadata?: Record<string, string | null>
}

export interface KnowledgeCatalog {
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
  scope: 'current_document'
  truncated: boolean
  source_kind: string
  warnings?: string[]
  reviewed_notes?: KnowledgeReviewNote[]
  original_pages?: { physical: number; section_id?: string | null; preview: boolean; printed_hint?: string }[]
  subsections?: KnowledgeDocument[]
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
