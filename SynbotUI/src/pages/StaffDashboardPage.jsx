import React from 'react'
import StaffDashboard from '../components/StaffDashboard'

export default function StaffDashboardPage() {
  const config = window.SYNBOT_CONFIG || {}
  const userId = config.userId || 'user:alice'
  const token = config.token || ''
  return (
    <div>
      <h2 className="text-xl font-semibold mb-4">Staff Dashboard</h2>
      <StaffDashboard userId={userId} token={token} />
    </div>
  )
}
