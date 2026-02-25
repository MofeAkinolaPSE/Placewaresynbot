import React, { useEffect, useState } from 'react'
import Form, { IChangeEvent, withTheme } from '@rjsf/core'
import { Theme as Bootstrap4Theme } from '@rjsf/bootstrap-4'

const RJSFForm = withTheme(Bootstrap4Theme)

export default function SchemaForm({ name }: { name: string }) {
  const [schema, setSchema] = useState<any | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (!name) return
    setLoading(true)
    setError(null)
    fetch(`/schemas/${encodeURIComponent(name)}`)
      .then(async (res) => {
        if (!res.ok) throw new Error(await res.text())
        return res.json()
      })
      .then((json) => setSchema(json))
      .catch((err) => setError(String(err)))
      .finally(() => setLoading(false))
  }, [name])

  function getSubmitPath(nameStr: string) {
    const n = (nameStr || '').toLowerCase()
    if (n.includes('inventory')) return '/inventory'
    if (n.includes('document') || n.includes('documents')) return '/documents'
    // fallback: post to a top-level route matching the schema name
    return `/${n}`
  }

  const [successMessage, setSuccessMessage] = useState<string | null>(null)

  async function handleSubmit(e: IChangeEvent<any>) {
    if (!schema) return
    const apiBase = (window as any).SYNBOT_CONFIG?.apiBaseUrl || ''
    const token = (window as any).SYNBOT_CONFIG?.token || (window as any).SYNBOT_CONFIG?.apiToken || ''
    const path = getSubmitPath(name)
    const url = `${apiBase.replace(/\/$/, '')}${path}`
    setSubmitting(true)
    setError(null)
    setSuccessMessage(null)
    try {
      const res = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token.replace(/^Bearer\s+/i, '')}` } : {})
        },
        body: JSON.stringify(e.formData)
      })
      if (!res.ok) {
        let text
        try { text = await res.text() } catch { text = `${res.status}` }
        throw new Error(text || `HTTP ${res.status}`)
      }
      const json = await res.json().catch(() => ({}))
      setSuccessMessage('Submitted successfully')
      console.log('submit response', json)
    } catch (err: any) {
      setError(err?.message || String(err))
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) return <div className="p-4">Loading schema...</div>
  if (!schema) return <div className="p-4">No schema</div>

  return (
    <div className="p-4 bg-white border rounded">
      <h3 className="text-lg font-semibold mb-2">{schema.title || name}</h3>
      {schema.description && <p className="text-sm text-gray-600 mb-2">{schema.description}</p>}
      {error && (
        <div className="alert alert-danger" role="alert">
          {error}
        </div>
      )}
      {successMessage && (
        <div className="alert alert-success alert-dismissible fade show" role="alert">
          {successMessage}
          <button type="button" className="close" data-dismiss="alert" aria-label="Close" onClick={() => setSuccessMessage(null)}>
            <span aria-hidden="true">&times;</span>
          </button>
        </div>
      )}

      <RJSFForm
        schema={schema}
        onSubmit={handleSubmit}
        onError={(errs) => console.warn('validation errors', errs)}
      >
        <div className="d-flex gap-2">
          <button type="submit" disabled={submitting} className="btn btn-primary">{submitting ? 'Submitting…' : 'Submit'}</button>
        </div>
      </RJSFForm>
    </div>
  )
}
