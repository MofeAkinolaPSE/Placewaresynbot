import "./global.css";

import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { HashRouter, Routes, Route } from "react-router-dom";
import AuthProvider from "./components/AuthProvider";
import ProtectedRoute from "./components/ProtectedRoute";
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import Executive from "./pages/Executive";
import FinanceAnalytics from "./pages/FinanceAnalytics";
import FinanceReports from "./pages/FinanceReports";
import ARAgingBucketDetails from "./pages/ARAgingBucketDetails";
import SageImport from "./pages/SageImport";
import HR from "./pages/HR";
import Operations from "./pages/Operations";
import ProjectControls from "./pages/ProjectControls";
import CRM from "./pages/CRM";
import AskSynbot from "./pages/AskSynbot";
import Workflow from "./pages/Workflow";
import Settings from "./pages/Settings";
import AdminUsers from "./pages/AdminUsers";
import Leads from "./pages/Leads";
import Login from "./pages/Login";
import NotFound from "./pages/NotFound";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Most dashboards update every few minutes; avoid refetching on every
      // tab focus and reuse results for at least 60 seconds.
      staleTime: 300_000,
      refetchOnWindowFocus: false,
      refetchOnReconnect: true,
      retry: 1,
    },
  },
});

const App = () => (
  <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      <Toaster />
      <Sonner />
      <AuthProvider>
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
              <Route path="/finance/analytics" element={<FinanceAnalytics />} />
              <Route path="/finance/reports" element={<FinanceReports />} />
              <Route path="/finance/reports/ar/:bucket" element={<ARAgingBucketDetails />} />
              <Route path="/finance/sage-import" element={<SageImport />} />
              <Route path="/hr" element={<HR />} />
              <Route path="/operations" element={<Operations />} />
              <Route path="/operations/project-controls" element={<ProjectControls />} />
              <Route path="/crm" element={<CRM />} />
              <Route path="/synbot" element={<AskSynbot />} />
              <Route path="/admin/leads" element={<Leads />} />
              <Route path="/workflow" element={<Workflow />} />
              <Route path="/admin/users" element={<AdminUsers />} />
              <Route path="/settings" element={<Settings />} />
            </Route>
            <Route path="*" element={<NotFound />} />
          </Routes>
        </HashRouter>
      </AuthProvider>
    </TooltipProvider>
  </QueryClientProvider>
);

export default App;
