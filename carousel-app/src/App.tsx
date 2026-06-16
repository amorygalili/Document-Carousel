import { useState, useEffect, useRef } from 'react'
import './App.css'

interface Document {
  id: string
  name: string
  description?: string
  type?: string
}


// When embedded, the tool stores documents in localStorage via the execute
// event (requires allowSameOrigin). Fall back to built-in defaults for local dev
// or when same-origin access is disabled.
function resolveDocuments(): Document[] {
  try {
    const stored = localStorage.getItem('carousel:documents')
    if (stored) return JSON.parse(stored) as Document[]
  } catch {
    // localStorage blocked (no allowSameOrigin) or invalid JSON — ignore
  }
  return DEFAULT_DOCUMENTS
}

const DEFAULT_DOCUMENTS: Document[] = [
  { id: '1', name: 'Project Requirements', description: 'Main project requirements document', type: 'pdf' },
  { id: '2', name: 'Technical Specification', description: 'Technical design specification', type: 'doc' },
  { id: '3', name: 'User Manual', description: 'End-user documentation', type: 'pdf' },
]

function getIcon(type?: string): string {
  switch (type?.toLowerCase()) {
    case 'pdf': return '📄'
    case 'doc':
    case 'docx': return '📝'
    case 'txt': return '📃'
    case 'xls':
    case 'xlsx': return '📊'
    case 'png':
    case 'jpg':
    case 'jpeg': return '🖼️'
    default: return '📁'
  }
}

interface DocumentCardProps {
  doc: Document
  selected: boolean
  onToggle: () => void
}

function DocumentCard({ doc, selected, onToggle }: DocumentCardProps) {
  return (
    <button
      className={`doc-card${selected ? ' doc-card--selected' : ''}`}
      onClick={onToggle}
      aria-pressed={selected}
      aria-label={`${selected ? 'Deselect' : 'Select'} ${doc.name}`}
    >
      {selected && <span className="doc-card__check" aria-hidden="true">✓</span>}
      <span className="doc-card__icon" aria-hidden="true">{getIcon(doc.type)}</span>
      <span className="doc-card__name">{doc.name}</span>
      {doc.description && (
        <span className="doc-card__desc">{doc.description}</span>
      )}
      {doc.type && (
        <span className="doc-card__type">{doc.type.toUpperCase()}</span>
      )}
    </button>
  )
}

const CARDS_PER_PAGE = 3

function App() {
  const [documents, setDocuments] = useState<Document[]>([])
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [pageIndex, setPageIndex] = useState(0)
  const [submitted, setSubmitted] = useState(false)
  const [requestId, setRequestId] = useState('')
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    setDocuments(resolveDocuments())
    try {
      setRequestId(localStorage.getItem('carousel:request_id') || '')
    } catch {
      // localStorage blocked — selection will fall back to postMessage
    }
  }, [])

  // Report height to parent so the iframe auto-sizes
  useEffect(() => {
    function reportHeight() {
      const h = document.documentElement.scrollHeight
      parent.postMessage({ type: 'iframe:height', height: h }, '*')
    }
    reportHeight()
    const observer = new ResizeObserver(reportHeight)
    observer.observe(document.body)
    return () => observer.disconnect()
  }, [documents, submitted])

  const totalPages = Math.ceil(documents.length / CARDS_PER_PAGE)
  const visibleDocs = documents.slice(pageIndex * CARDS_PER_PAGE, (pageIndex + 1) * CARDS_PER_PAGE)

  const toggleSelect = (id: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const handleSubmit = () => {
    const ids = Array.from(selectedIds)
    if (ids.length === 0) return
    try {
      // Hand the selection back to the tool, which is polling localStorage.
      localStorage.setItem('carousel:selection', JSON.stringify({ requestId, ids }))
    } catch {
      // localStorage blocked — fall back to submitting document names as a prompt.
      const selected = documents.filter(d => selectedIds.has(d.id))
      const names = selected.map(d => d.name).join(', ')
      const text = `Please use the following documents as context: ${names}`
      parent.postMessage({ type: 'input:prompt:submit', text }, '*')
    }
    setSubmitted(true)
  }

  if (submitted) {
    return (
      <div className="submitted" ref={containerRef}>
        <span className="submitted__icon">✓</span>
        <p className="submitted__text">Documents added to chat!</p>
      </div>
    )
  }

  return (
    <div className="carousel-root" ref={containerRef}>
      <div className="carousel-header">
        <h2 className="carousel-title">Select Documents</h2>
        <p className="carousel-subtitle">
          {selectedIds.size > 0
            ? `${selectedIds.size} document${selectedIds.size !== 1 ? 's' : ''} selected`
            : 'Click a document card to select it'}
        </p>
      </div>

      <div className="carousel-row">
        <button
          className="nav-btn"
          onClick={() => setPageIndex(i => i - 1)}
          disabled={pageIndex === 0}
          aria-label="Previous page"
        >
          ‹
        </button>

        <div className="cards-container">
          {visibleDocs.map(doc => (
            <DocumentCard
              key={doc.id}
              doc={doc}
              selected={selectedIds.has(doc.id)}
              onToggle={() => toggleSelect(doc.id)}
            />
          ))}
          {/* Fill empty slots so the layout stays stable */}
          {Array.from({ length: CARDS_PER_PAGE - visibleDocs.length }).map((_, i) => (
            <div key={`empty-${i}`} className="doc-card doc-card--empty" aria-hidden="true" />
          ))}
        </div>

        <button
          className="nav-btn"
          onClick={() => setPageIndex(i => i + 1)}
          disabled={pageIndex >= totalPages - 1}
          aria-label="Next page"
        >
          ›
        </button>
      </div>

      {totalPages > 1 && (
        <div className="pagination" role="tablist" aria-label="Carousel pages">
          {Array.from({ length: totalPages }, (_, i) => (
            <button
              key={i}
              className={`pagination__dot${i === pageIndex ? ' pagination__dot--active' : ''}`}
              onClick={() => setPageIndex(i)}
              aria-label={`Go to page ${i + 1}`}
              aria-selected={i === pageIndex}
              role="tab"
            />
          ))}
        </div>
      )}

      <button
        className="submit-btn"
        onClick={handleSubmit}
        disabled={selectedIds.size === 0}
      >
        {selectedIds.size === 0
          ? 'Select documents to add'
          : `Add ${selectedIds.size} document${selectedIds.size !== 1 ? 's' : ''} to Chat`}
      </button>
    </div>
  )
}

export default App
