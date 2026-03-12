import React, { useState, useRef, useCallback } from 'react'

// ── File-type metadata mirroring the backend registry ──────────────────────
const FILE_TYPES = [
  {
    file_type: 'chart_of_accounts',
    label: 'Chart of Accounts',
    icon: '📒',
    description: 'Account code hierarchy (COA)',
    required: ['account_id', 'account_code', 'account_name'],
  },
  {
    file_type: 'vendors',
    label: 'Vendors',
    icon: '🏭',
    description: 'Supplier master list',
    required: ['vendor_id', 'vendor_name'],
  },
  {
    file_type: 'customers',
    label: 'Customers',
    icon: '🏥',
    description: 'Customer master list',
    required: ['customer_id', 'name'],
  },
  {
    file_type: 'items',
    label: 'Product Items',
    icon: '💊',
    description: 'Product / SKU catalogue',
    required: ['item_id', 'item_name'],
  },
  {
    file_type: 'stock_on_hand',
    label: 'Stock on Hand',
    icon: '📦',
    description: 'Current warehouse inventory',
    required: ['item_id', 'quantity_on_hand'],
  },
  {
    file_type: 'purchase_orders',
    label: 'Purchase Orders',
    icon: '🧾',
    description: 'Supplier PO history',
    required: ['po_id', 'po_number'],
  },
  {
    file_type: 'sales_invoices',
    label: 'Sales Invoices',
    icon: '📄',
    description: 'AR invoice register',
    required: ['invoice_id', 'customer_id', 'net_amount', 'status'],
  },
  {
    file_type: 'sales_invoice_lines',
    label: 'Invoice Lines',
    icon: '📋',
    description: 'Per-line revenue & margin detail',
    required: ['line_id', 'invoice_id'],
  },
  {
    file_type: 'inventory_transactions',
    label: 'Inventory Transactions',
    icon: '🔄',
    description: 'Stock movement ledger',
    required: ['transaction_id'],
  },
  {
    file_type: 'gl_journal_entries',
    label: 'GL Journal Entries',
    icon: '📊',
    description: 'General Ledger double-entry journal',
    required: ['account_id', 'debit_amount', 'credit_amount', 'posting_date'],
  },
]

// ── Status helpers ──────────────────────────────────────────────────────────
const STATUS_STYLES = {
  idle: 'bg-muted text-muted-foreground',
  uploading: 'bg-blue-100 text-blue-700',
  success: 'bg-green-100 text-green-700',
  error: 'bg-red-100 text-red-700',
}

const STATUS_LABELS = {
  idle: 'Ready',
  uploading: 'Uploading…',
  success: 'Imported',
  error: 'Failed',
}

// ── Upload hook ─────────────────────────────────────────────────────────────
function useUploadState() {
  const [states, setStates] = useState(() =>
    Object.fromEntries(FILE_TYPES.map((ft) => [ft.file_type, { status: 'idle', file: null, result: null }]))
  )

  const setFileForType = useCallback((file_type, file) => {
    setStates((prev) => ({
      ...prev,
      [file_type]: { ...prev[file_type], file, status: 'idle', result: null },
    }))
  }, [])

  const setStatus = useCallback((file_type, status, result = null) => {
    setStates((prev) => ({
      ...prev,
      [file_type]: { ...prev[file_type], status, result },
    }))
  }, [])

  return { states, setFileForType, setStatus }
}

// ── Individual upload card ───────────────────────────────────────────────────
function ImportCard({ meta, state, onFileChange, onUpload }) {
  const inputRef = useRef(null)
  const { status, file, result } = state

  return (
    <div className="bg-card border border-border rounded-lg p-4 flex flex-col gap-3 shadow-sm">
      {/* Header */}
      <div className="flex items-center gap-2">
        <span className="text-2xl">{meta.icon}</span>
        <div>
          <h3 className="font-semibold text-sm">{meta.label}</h3>
          <p className="text-xs text-muted-foreground">{meta.description}</p>
        </div>
        <span
          className={`ml-auto text-xs font-medium px-2 py-0.5 rounded-full ${STATUS_STYLES[status]}`}
        >
          {STATUS_LABELS[status]}
        </span>
      </div>

      {/* Required columns hint */}
      <div className="text-xs text-muted-foreground">
        Required:{' '}
        <code className="bg-muted px-1 rounded">{meta.required.join(', ')}</code>
      </div>

      {/* File picker */}
      <div className="flex items-center gap-2">
        <input
          ref={inputRef}
          type="file"
          accept=".csv"
          className="hidden"
          onChange={(e) => onFileChange(e.target.files?.[0] || null)}
        />
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          className="text-xs px-3 py-1.5 rounded border border-border bg-background hover:bg-muted transition"
        >
          {file ? '📁 ' + file.name : 'Choose CSV'}
        </button>

        {/* Upload button */}
        <button
          type="button"
          disabled={!file || status === 'uploading'}
          onClick={onUpload}
          className="ml-auto text-xs px-3 py-1.5 rounded bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-40 transition"
        >
          {status === 'uploading' ? 'Uploading…' : 'Upload'}
        </button>
      </div>

      {/* Result detail */}
      {result && status === 'success' && (
        <div className="text-xs text-green-700 bg-green-50 rounded p-2">
          ✓ {result.rows_inserted} rows imported • batch{' '}
          <code className="font-mono">{result.batch_id?.slice(0, 8)}…</code>
          {result.validation_error_count > 0 && (
            <span className="text-yellow-600 ml-1">
              ({result.validation_error_count} validation warnings)
            </span>
          )}
        </div>
      )}
      {result && status === 'error' && (
        <div className="text-xs text-red-700 bg-red-50 rounded p-2 overflow-auto max-h-24">
          ✗ {typeof result === 'string' ? result : result.detail || JSON.stringify(result)}
        </div>
      )}
    </div>
  )
}

// ── Batch upload bar ─────────────────────────────────────────────────────────
function BatchUploadBar({ states, onUploadAll }) {
  const readyCount = Object.values(states).filter((s) => s.file && s.status === 'idle').length
  const successCount = Object.values(states).filter((s) => s.status === 'success').length

  return (
    <div className="flex items-center gap-4 bg-card border border-border rounded-lg px-4 py-3 mb-6">
      <div className="text-sm text-muted-foreground">
        {successCount > 0 && (
          <span className="text-green-600 font-medium">{successCount} imported · </span>
        )}
        {readyCount > 0 ? (
          <span>{readyCount} file(s) ready to upload</span>
        ) : (
          <span>Select CSV files for each dataset below</span>
        )}
      </div>
      <button
        type="button"
        disabled={readyCount === 0}
        onClick={onUploadAll}
        className="ml-auto text-sm px-4 py-1.5 rounded bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-40 transition"
      >
        Upload All Ready ({readyCount})
      </button>
    </div>
  )
}

// ── Recent jobs table ────────────────────────────────────────────────────────
function RecentJobs({ jobs }) {
  if (!jobs || jobs.length === 0) return null
  return (
    <div className="mt-8">
      <h3 className="text-sm font-semibold mb-3">Recent Import Jobs</h3>
      <div className="overflow-x-auto rounded-lg border border-border text-xs">
        <table className="w-full">
          <thead className="bg-muted text-muted-foreground">
            <tr>
              {['File Type', 'Status', 'Rows', 'Batch', 'Imported At'].map((h) => (
                <th key={h} className="text-left px-3 py-2 font-medium">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {jobs.map((j) => (
              <tr key={j.id} className="border-t border-border hover:bg-muted/40">
                <td className="px-3 py-2">{j.metadata?.file_type || j.domain}</td>
                <td className="px-3 py-2">
                  <span
                    className={`px-1.5 py-0.5 rounded-full ${
                      j.status === 'succeeded' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'
                    }`}
                  >
                    {j.status}
                  </span>
                </td>
                <td className="px-3 py-2">{j.row_count ?? '—'}</td>
                <td className="px-3 py-2 font-mono">{j.batch_id?.slice(0, 8)}…</td>
                <td className="px-3 py-2">{j.imported_at?.slice(0, 19).replace('T', ' ')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── Main page ────────────────────────────────────────────────────────────────
export default function SageImport() {
  const config = window.SYNBOT_CONFIG || {}
  const apiBase = config.apiBaseUrl || ''
  const token = config.token || ''

  const { states, setFileForType, setStatus } = useUploadState()
  const [jobs, setJobs] = useState([])
  const [jobsLoading, setJobsLoading] = useState(false)

  // Build auth headers
  const authHeaders = token ? { Authorization: `Bearer ${token}` } : {}

  // ── Single-file upload ──────────────────────────────────────────────────
  const uploadOne = useCallback(
    async (file_type) => {
      const { file } = states[file_type]
      if (!file) return

      setStatus(file_type, 'uploading')

      const form = new FormData()
      form.append('file_type', file_type)
      form.append('file', file)

      try {
        const res = await fetch(`${apiBase}/sage/import/csv`, {
          method: 'POST',
          headers: authHeaders,
          body: form,
        })
        const data = await res.json()
        if (!res.ok) {
          setStatus(file_type, 'error', data)
        } else {
          setStatus(file_type, 'success', data)
        }
      } catch (err) {
        setStatus(file_type, 'error', err.message || 'Network error')
      }
    },
    [states, apiBase, authHeaders, setStatus]
  )

  // ── Batch upload all idle ready files ──────────────────────────────────
  const uploadAll = useCallback(async () => {
    const ready = FILE_TYPES.filter(
      (ft) => states[ft.file_type].file && states[ft.file_type].status === 'idle'
    )
    // Sequential to avoid overwhelming the server
    for (const ft of ready) {
      await uploadOne(ft.file_type)
    }
    loadJobs()
  }, [states, uploadOne])

  // ── Load recent jobs ────────────────────────────────────────────────────
  const loadJobs = useCallback(async () => {
    setJobsLoading(true)
    try {
      const res = await fetch(`${apiBase}/sage/import/jobs?limit=20`, {
        headers: authHeaders,
      })
      if (res.ok) {
        const data = await res.json()
        setJobs(data.jobs || [])
      }
    } catch (_) {
      // Jobs table is best-effort
    } finally {
      setJobsLoading(false)
    }
  }, [apiBase, authHeaders])

  // Load jobs on mount
  React.useEffect(() => {
    loadJobs()
  }, [loadJobs])

  return (
    <div>
      {/* Page header */}
      <div className="mb-6">
        <h2 className="text-xl font-semibold">Data Import — Sage CSV Package</h2>
        <p className="text-sm text-muted-foreground mt-1">
          Upload the 10-file PlacewareBot data package. Each file is validated,
          mapped and stored in the corresponding snapshot table.
        </p>
      </div>

      {/* Batch bar */}
      <BatchUploadBar states={states} onUploadAll={uploadAll} />

      {/* Cards grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {FILE_TYPES.map((meta) => (
          <ImportCard
            key={meta.file_type}
            meta={meta}
            state={states[meta.file_type]}
            onFileChange={(file) => setFileForType(meta.file_type, file)}
            onUpload={() => {
              uploadOne(meta.file_type).then(loadJobs)
            }}
          />
        ))}
      </div>

      {/* Recent jobs */}
      <div className="flex items-center justify-between mt-8 mb-2">
        <span className="text-sm font-semibold">Recent Import Jobs</span>
        <button
          onClick={loadJobs}
          className="text-xs px-3 py-1 rounded border border-border hover:bg-muted transition"
          disabled={jobsLoading}
        >
          {jobsLoading ? 'Loading…' : '↻ Refresh'}
        </button>
      </div>
      <RecentJobs jobs={jobs} />
    </div>
  )
}
