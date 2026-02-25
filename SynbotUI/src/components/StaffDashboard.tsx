import React, { useEffect, useState } from 'react'

type Activity = {
  event_id?: string
  timestamp: string
  department: string
  event_type: string
  summary?: string
  payload?: Record<string, any>
}

type PendingApproval = {
  event_id?: string
  event_type: string
  created_by?: string
  timestamp: string
  reason?: string
}

type TaskItem = {
  task_id: string
  title: string
  description?: string
  assigned_to?: string
  status: string
  due_date?: string | null
}

type KPI = { key: string; label: string; value: any }
type Badge = { id: string; name: string; description?: string }

type StaffDashboardModel = {
  user_id: string
  activities: Activity[]
  pending_approvals: PendingApproval[]
  tasks: TaskItem[]
  kpis: KPI[]
  badges: Badge[]
}

export default function StaffDashboard({ userId, token }: { userId: string; token?: string }) {
  const [data, setData] = useState<StaffDashboardModel | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchData()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId, token])

  async function fetchData() {
    setLoading(true)
    setError(null)
    try {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' }
      if (token) headers['Authorization'] = `Bearer ${token.replace(/^Bearer\s+/i, '')}`
      const res = await fetch(`/staff/${encodeURIComponent(userId)}/dashboard`, { headers })
      if (!res.ok) {
        const t = await res.text()
        throw new Error(t || `HTTP ${res.status}`)
      }
      const json = await res.json()
      setData(json)
    } catch (err: any) {
      setError(err?.message || String(err))
      setData(null)
    } finally {
      setLoading(false)
    }
  }

  if (loading) return <div className="p-4">Loading...</div>
  if (error) return <div className="p-4 text-red-600">Error: {error}</div>
  if (!data) return <div className="p-4">No data</div>

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-4">
        {data.kpis.map((k) => (
          <div key={k.key} className="p-4 bg-white border rounded">
            <div className="text-sm text-gray-500">{k.label}</div>
            <div className="text-2xl font-semibold">{String(k.value)}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-3 gap-4">
        <div className="col-span-2 p-4 bg-white border rounded">
          <h3 className="font-semibold mb-2">Activities</h3>
          <div className="space-y-2 max-h-72 overflow-auto">
            {data.activities.map((a) => (
              <div key={a.event_id || a.timestamp} className="p-2 border rounded">
                <div className="text-sm text-gray-600">{a.timestamp} · {a.department}</div>
                <div className="font-medium">{a.event_type}</div>
                <pre className="text-xs mt-1 bg-gray-50 p-2 rounded">{JSON.stringify(a.payload || {}, null, 2)}</pre>
              </div>
            ))}
          </div>
        </div>

        <div className="p-4 bg-white border rounded">
          <h3 className="font-semibold mb-2">Pending Approvals</h3>
          <div className="space-y-2 max-h-72 overflow-auto">
            {data.pending_approvals.map((p) => (
              <div key={p.event_id || p.timestamp} className="p-2 border rounded">
                <div className="text-sm text-gray-600">{p.timestamp}</div>
                <div className="font-medium">{p.event_type}</div>
                <div className="text-xs text-gray-500">Requested by {p.created_by}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="p-4 bg-white border rounded">
        <h3 className="font-semibold mb-2">Tasks</h3>
        <div className="space-y-2 max-h-72 overflow-auto">
          {data.tasks.map((t) => (
            <div key={t.task_id} className="p-2 border rounded">
              <div className="flex justify-between">
                <div className="font-medium">{t.title}</div>
                <div className="text-sm text-gray-500">{t.status}</div>
              </div>
              <div className="text-xs text-gray-600">{t.description}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="flex gap-2">
        {data.badges.map((b) => (
          <div key={b.id} className="px-3 py-1 bg-green-50 border border-green-200 rounded text-sm">{b.name}</div>
        ))}
      </div>
    </div>
  )
}
