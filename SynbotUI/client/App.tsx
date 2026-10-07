import "./global.css";

import { lazy, Suspense } from "react";

import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { HashRouter, Navigate, Routes, Route } from "react-router-dom";
import ThemeProvider from "./components/theme-provider";
import AuthProvider from "./components/AuthProvider";
import SessionPrewarm from "./components/SessionPrewarm";
import PresenceHeartbeat from "./components/PresenceHeartbeat";
import ProtectedRoute from "./components/ProtectedRoute";
import LicenseGate from "./components/LicenseGate";
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import Executive from "./pages/Executive";
import ExecutiveSummaryDetails from "./pages/ExecutiveSummaryDetails";
import SageImport from "./pages/SageImport";
import HR from "./pages/HR";
import Inventory from "./pages/Inventory";
import Operations from "./pages/Operations";
import ProjectControls from "./pages/ProjectControls";
import Suppliers from "./pages/Suppliers";
import CRM from "./pages/CRM";
import AskSynbot from "./pages/AskSynbot";
import CalendarTaskManager from "./pages/CalendarTaskManager";
import LogisticsCalendar from "./pages/LogisticsCalendar";
import AgentsDashboard from "./pages/AgentsDashboard";
import AgentDetail from "./pages/AgentDetail";
import Workflow from "./pages/Workflow";
import Settings from "./pages/Settings";
import AdminUsers from "./pages/AdminUsers";
import DataIntelligence from "./pages/DataIntelligence";
import CustomerWorkspace from "./pages/CustomerWorkspace";
import Leads from "./pages/Leads";
import StaffWorkspace from "./pages/StaffWorkspace";
import CRMLeadFinder from "./pages/CRMLeadFinder";
import CRMCustomers from "./pages/CRMCustomers";
import Compliance from "./pages/Compliance";
import SalesCRM from "./pages/SalesCRM";
import Frontdesk from "./pages/Frontdesk";
import AllInvoices from "./pages/AllInvoices";
import QualityControl from "./pages/QualityControl";
import QualityHub from "./pages/QualityHub";
import LogisticsMonitor from "./pages/LogisticsMonitor";
import FinanceAR from "./pages/FinanceAR";
import { DrillProvider } from "./components/books/lineage";
import Login from "./pages/Login";
import RiderTrack from "./pages/RiderTrack";
import RiderSignIn from "./pages/RiderSignIn";
import ReportWizard from "./pages/ReportWizard";
import ReportComposer from "./pages/ReportComposer";
import ReportLibrary from "./pages/ReportLibrary";
import PurchaseOrders from "./pages/PurchaseOrders";
import NotFound from "./pages/NotFound";

// ACE Books (finance engine) - loaded on demand so the rest of the app stays light.
const BooksOverview = lazy(() => import("./pages/books/BooksOverview"));
const BooksSales = lazy(() => import("./pages/books/BooksSales"));
const BooksPurchases = lazy(() => import("./pages/books/BooksPurchases"));
const BooksStock = lazy(() => import("./pages/books/BooksStock"));
const BooksBanking = lazy(() => import("./pages/books/BooksBanking"));
const BooksLedger = lazy(() => import("./pages/books/BooksLedger"));
const BooksStatements = lazy(() => import("./pages/books/BooksStatements"));
const BooksAssets = lazy(() => import("./pages/books/BooksAssets"));
const BooksClose = lazy(() => import("./pages/books/BooksClose"));
const BooksSetup = lazy(() => import("./pages/books/BooksSetup"));
const BooksReports = lazy(() => import("./pages/books/BooksReports"));
const InvoicePrint = lazy(() => import("./pages/books/InvoicePrint"));
const books = (el: JSX.Element) => <Suspense fallback={<div className="p-8 text-sm text-muted-foreground">Loading ACE Books…</div>}>{el}</Suspense>;

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 180_000,
      gcTime: 1_800_000,
      refetchOnMount: false,
      refetchOnWindowFocus: false,
      refetchOnReconnect: true,
      refetchIntervalInBackground: false,
      retry: 1,
    },
  },
});

const App = () => (
  <QueryClientProvider client={queryClient}>
    <ThemeProvider attribute="class" defaultTheme="light" disableTransitionOnChange>
      <TooltipProvider>
        <Toaster />
        <Sonner />
        <AuthProvider>
          <SessionPrewarm />
          <PresenceHeartbeat />
          <LicenseGate>
          <HashRouter>
            <Routes>
              <Route path="/login" element={<Login />} />
              {/* the printed invoice: a page of its own (no sidebar) */}
              <Route path="/finance/books/invoice-print/:kind/:id" element={<ProtectedRoute>{books(<InvoicePrint />)}</ProtectedRoute>} />
              <Route
                element={
                  <ProtectedRoute>
                    <Layout />
                  </ProtectedRoute>
                }
              >
                <Route path="/" element={<Dashboard />} />
                <Route path="/executive" element={<Executive />} />
                <Route path="/executive/summary" element={<ExecutiveSummaryDetails />} />
                {/* Analytics and Reports duplicated ACE Books from Sage snapshots; they now open the ACE Books screens.
                    Credit Control & Alerts keeps its own features but reads ACE Books (src/fin/readmodel.py). */}
                <Route path="/finance/analytics" element={<Navigate to="/finance/books" replace />} />
                <Route path="/finance/reports" element={<Navigate to="/finance/books/reports" replace />} />
                <Route path="/finance/ar" element={<DrillProvider><FinanceAR /></DrillProvider>} />
                {/* Receipts, supplier payments and budgets are recorded once, in ACE Books; the old
                    pages wrote to separate tables, so their URLs now open the ACE Books screens. */}
                <Route path="/finance/ar/receipts" element={<Navigate to="/finance/books/sales?tab=receipts" replace />} />
                <Route path="/finance/vendor-payments" element={<Navigate to="/finance/books/purchases?tab=payments" replace />} />
                <Route path="/finance/budget" element={<Navigate to="/finance/books/setup?tab=budgets" replace />} />
                <Route path="/finance/sage-import" element={<SageImport />} />
                <Route path="/finance/books" element={books(<BooksOverview />)} />
                <Route path="/finance/books/sales" element={books(<BooksSales />)} />
                <Route path="/finance/books/purchases" element={books(<BooksPurchases />)} />
                <Route path="/finance/books/stock" element={books(<BooksStock />)} />
                <Route path="/finance/books/banking" element={books(<BooksBanking />)} />
                <Route path="/finance/books/ledger" element={books(<BooksLedger />)} />
                <Route path="/finance/books/statements" element={books(<BooksStatements />)} />
                <Route path="/finance/books/assets" element={books(<BooksAssets />)} />
                <Route path="/finance/books/close" element={books(<BooksClose />)} />
                <Route path="/finance/books/setup" element={books(<BooksSetup />)} />
                <Route path="/finance/books/reports" element={books(<BooksReports />)} />
                <Route path="/hr" element={<HR />} />
                <Route path="/inventory" element={<Inventory />} />
                <Route path="/operations" element={<Operations />} />
                <Route path="/operations/project-controls" element={<ProjectControls />} />
                <Route path="/operations/suppliers" element={<Suppliers />} />
                <Route path="/operations/purchase-orders" element={<PurchaseOrders />} />
                <Route path="/operations/logistics" element={<LogisticsMonitor />} />
                <Route path="/crm" element={<CRM />} />
                <Route path="/customers/workspace" element={<CustomerWorkspace />} />
                <Route path="/crm/lead-finder" element={<CRMLeadFinder />} />
                <Route path="/crm/customers" element={<CRMCustomers />} />
                <Route path="/crm/sales" element={<SalesCRM />} />
                <Route path="/frontdesk" element={<Frontdesk />} />
                <Route path="/frontdesk/invoices" element={<AllInvoices />} />
                <Route path="/quality" element={<QualityHub />} />
                <Route path="/quality-control" element={<QualityControl />} />
                <Route path="/synbot" element={<AskSynbot />} />
                <Route path="/calendar" element={<LogisticsCalendar />} />
                <Route path="/calendar/tasks" element={<CalendarTaskManager />} />
                <Route path="/agents" element={<AgentsDashboard />} />
                <Route path="/agents/:name" element={<AgentDetail />} />
                <Route path="/admin/leads" element={<Navigate to="/crm/lead-finder?tab=inbound" replace />} />
                <Route path="/compliance" element={<Compliance />} />
                <Route path="/workflow" element={<Workflow />} />
                <Route path="/workspace" element={<StaffWorkspace />} />
                {/* the three old staff pages are now tabs of My Workspace */}
                <Route path="/staff/dashboard" element={<Navigate to="/workspace" replace />} />
                <Route path="/staff/collaboration" element={<Navigate to="/workspace?tab=messages" replace />} />
                <Route path="/staff/time-tracker" element={<Navigate to="/workspace?tab=progress" replace />} />
                <Route path="/admin/users" element={<AdminUsers />} />
                <Route path="/admin/data-intelligence" element={<DataIntelligence />} />
                <Route path="/settings" element={<Settings />} />
                <Route path="/reports/new" element={<ReportComposer />} />
                <Route path="/reports/classic" element={<ReportWizard />} />
                <Route path="/reports" element={<ReportLibrary />} />
              </Route>
              <Route path="/rider-track/:token" element={<RiderTrack />} />
              <Route path="/rider" element={<RiderSignIn />} />
              <Route path="*" element={<NotFound />} />
            </Routes>
          </HashRouter>
          </LicenseGate>
        </AuthProvider>
      </TooltipProvider>
    </ThemeProvider>
  </QueryClientProvider>
);

export default App;
