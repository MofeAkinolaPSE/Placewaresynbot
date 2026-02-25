import { HashRouter, Routes, Route, NavLink } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import Settings from './pages/Settings'
import SageImport from './pages/SageImport'
import FinanceAnalytics from './pages/FinanceAnalytics'
import FinanceReports from './pages/FinanceReports'
import HR from './pages/HR'
import Operations from './pages/Operations'
import CRM from './pages/CRM'
import AskSynbot from './pages/AskSynbot'
import Workflow from './pages/Workflow'
import Index from './pages/Index'
import NotFound from './pages/NotFound'
import StaffDashboardPage from './pages/StaffDashboardPage'
import SchemaFormPage from './pages/SchemaFormPage'

export default function App() {
  const config = window.SYNBOT_CONFIG || {}

  const navItems = [
    { to: '/dashboard', label: 'Dashboard' },
    { to: '/staff', label: 'Staff' },
    { to: '/forms/inventory_item', label: 'Forms' },
    { to: '/settings', label: 'Settings' },
    { to: '/import', label: 'Data Import' },
    { to: '/analytics', label: 'Finance Analytics' },
    { to: '/reports', label: 'Finance Reports' },
    { to: '/hr', label: 'HR' },
    { to: '/ops', label: 'Operations' },
    { to: '/crm', label: 'CRM' },
    { to: '/synbot', label: 'Ask Synbot' },
    { to: '/workflow', label: 'Workflow' }
  ]

  return (
    <HashRouter>
      <div className="min-h-screen bg-background text-foreground">
        <header className="border-b border-border bg-card">
          <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
            <div>
              <h1 className="text-xl font-semibold">Synbot Admin</h1>
              <p className="text-xs text-muted-foreground">
                Role: {config.role || 'guest'} · API: {config.apiBaseUrl || 'not set'}
              </p>
            </div>
            <nav className="flex flex-wrap gap-3 text-sm">
              {navItems.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={({ isActive }) =>
                    `px-2 py-1 rounded ${isActive ? 'bg-primary text-primary-foreground' : 'hover:bg-muted'}`
                  }
                >
                  {item.label}
                </NavLink>
              ))}
            </nav>
          </div>
        </header>

        <main className="max-w-7xl mx-auto px-4 py-6">
          <Routes>
            <Route path="/" element={<Index />} />
            <Route path="/dashboard" element={<Dashboard />} />
              <Route path="/staff" element={<StaffDashboardPage />} />
            <Route path="/forms/:name" element={<SchemaFormPage />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="/import" element={<SageImport />} />
            <Route path="/analytics" element={<FinanceAnalytics />} />
            <Route path="/reports" element={<FinanceReports />} />
            <Route path="/hr" element={<HR />} />
            <Route path="/ops" element={<Operations />} />
            <Route path="/crm" element={<CRM />} />
            <Route path="/synbot" element={<AskSynbot />} />
            <Route path="/workflow" element={<Workflow />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </main>
      </div>
    </HashRouter>
  )
}
