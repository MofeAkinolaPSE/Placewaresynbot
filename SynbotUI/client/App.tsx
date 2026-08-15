import "./global.css";

import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { HashRouter, Routes, Route } from "react-router-dom";
import ThemeProvider from "./components/theme-provider";
import AuthProvider from "./components/AuthProvider";
import SessionPrewarm from "./components/SessionPrewarm";
import PresenceHeartbeat from "./components/PresenceHeartbeat";
import ProtectedRoute from "./components/ProtectedRoute";
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import Executive from "./pages/Executive";
import ExecutiveSummaryDetails from "./pages/ExecutiveSummaryDetails";
import FinanceAnalytics from "./pages/FinanceAnalytics";
import FinanceReports from "./pages/FinanceReports";
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
import ARReceipts from "./pages/ARReceipts";
import CustomerWorkspace from "./pages/CustomerWorkspace";
import Leads from "./pages/Leads";
import StaffDashboard from "./pages/StaffDashboard";
import StaffCollaboration from "./pages/StaffCollaboration";
import StaffTimeTracker from "./pages/StaffTimeTracker";
import CRMLeadFinder from "./pages/CRMLeadFinder";
import Compliance from "./pages/Compliance";
import SalesCRM from "./pages/SalesCRM";
import Frontdesk from "./pages/Frontdesk";
import QualityControl from "./pages/QualityControl";
import LogisticsMonitor from "./pages/LogisticsMonitor";
import FinanceAR from "./pages/FinanceAR";
import FinanceVendorPayments from "./pages/FinanceVendorPayments";
import FinanceBudget from "./pages/FinanceBudget";
import Login from "./pages/Login";
import RiderTrack from "./pages/RiderTrack";
import RiderSignIn from "./pages/RiderSignIn";
import ReportWizard from "./pages/ReportWizard";
import ReportLibrary from "./pages/ReportLibrary";
import PurchaseOrders from "./pages/PurchaseOrders";
import NotFound from "./pages/NotFound";

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
          <HashRouter>
            <Routes>
              <Route path="/login" element={<Login />} />
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
                <Route path="/finance/analytics" element={<FinanceAnalytics />} />
                <Route path="/finance/reports" element={<FinanceReports />} />
                <Route path="/finance/ar" element={<FinanceAR />} />
                <Route path="/finance/ar/receipts" element={<ARReceipts />} />
                <Route path="/finance/vendor-payments" element={<FinanceVendorPayments />} />
                <Route path="/finance/budget" element={<FinanceBudget />} />
                <Route path="/finance/sage-import" element={<SageImport />} />
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
                <Route path="/crm/sales" element={<SalesCRM />} />
                <Route path="/frontdesk" element={<Frontdesk />} />
                <Route path="/quality-control" element={<QualityControl />} />
                <Route path="/synbot" element={<AskSynbot />} />
                <Route path="/calendar" element={<LogisticsCalendar />} />
                <Route path="/calendar/tasks" element={<CalendarTaskManager />} />
                <Route path="/agents" element={<AgentsDashboard />} />
                <Route path="/agents/:name" element={<AgentDetail />} />
                <Route path="/admin/leads" element={<Leads />} />
                <Route path="/compliance" element={<Compliance />} />
                <Route path="/workflow" element={<Workflow />} />
                <Route path="/staff/dashboard" element={<StaffDashboard />} />
                <Route path="/staff/collaboration" element={<StaffCollaboration />} />
                <Route path="/staff/time-tracker" element={<StaffTimeTracker />} />
                <Route path="/admin/users" element={<AdminUsers />} />
                <Route path="/admin/data-intelligence" element={<DataIntelligence />} />
                <Route path="/settings" element={<Settings />} />
                <Route path="/reports/new" element={<ReportWizard />} />
                <Route path="/reports" element={<ReportLibrary />} />
              </Route>
              <Route path="/rider-track/:token" element={<RiderTrack />} />
              <Route path="/rider" element={<RiderSignIn />} />
              <Route path="*" element={<NotFound />} />
            </Routes>
          </HashRouter>
        </AuthProvider>
      </TooltipProvider>
    </ThemeProvider>
  </QueryClientProvider>
);

export default App;
