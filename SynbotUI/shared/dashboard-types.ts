
// Phase 1: Inventory
export interface InventorySummaryItem {
  sku: string;
  name: string;
  baseline: {
    quantity: number;
    source: string;
    as_of: string;
  };
  events: {
    count: number;
    net_change: number;
  };
  current_stock: number;
  status: "In Stock" | "Out of Stock";
}

export interface InventoryDashboardData {
  summary: {
    total_active_skus: number;
    low_stock_count: number;
    /** Active products (future expiry or traded this period) at zero stock. */
    out_of_stock_count: number;
    /** All catalog items at zero stock, including dead/inactive history. */
    catalog_zero_stock_count?: number;
  };
  critical_items: InventorySummaryItem[];
  recent_movements: InventoryMovement[];
}

export interface InventoryMovement {
  id: string | number;
  sku: string;
  quantity_change: number;
  movement_type: string;
  occurred_at: string;
}

// Phase 2: Staff & Ops
export interface StaffMember {
  staff_id: string;
  full_name: string;
  email: string;
  department: string;
  role: string;
  status: "active" | "inactive";
}

export interface TimesheetEntry {
  id: number | string;
  staff?: { full_name?: string | null };
  staff_id?: string | number | null;
  date: string;
  hours_worked: number;
  department: string;
  activity_note?: string;
}

export interface StaffDirectoryEntry {
  staff_id?: string | number;
  full_name: string;
  email: string;
  department?: string;
  role?: string;
  status?: string;
}

export interface WorkforceDashboardData {
  period: string;
  total_hours: number;
  active_staff_count: number;
  department_breakdown: Record<string, number>;
}

// Phase 3: Intelligence
export interface Alert {
  id: number;
  title: string;
  message: string;
  severity: "info" | "warning" | "critical";
  category: "finance" | "inventory" | "workforce" | "system";
  created_at: string;
}

export interface ExecutiveBriefing {
  generated_at: string;
  summary: {
    health_score: string;
    critical_risks: string[];
    focus_area: string;
  };
  finance_brief: {
    cash_outstanding: number;
    cash_payable: number;
  };
  inventory_brief: {
    low_stock_alerts: number;
  };
  workforce_brief: {
    weekly_hours: number;
    top_dept: string;
  };
  latest_alerts: string[];
}

export interface TrendFlag {
  trend?: "Improving" | "Declining" | "Flat" | string;
  change_pct?: number;
}

export interface ExecutiveSummaryResponse {
  status: "Healthy" | "Stable" | "At Risk" | string;
  key_findings: string[];
  recommended_focus: string[];
  sources?: string[];
}

export interface RiskSignal {
  domain: "Finance" | "Ops" | "HR" | "CRM" | "Inventory" | string;
  risk_type: string;
  severity: "Low" | "Medium" | "High" | string;
  signal: string;
  data_source: string;
}

export interface OpportunitySignal {
  risk: string;
  opportunity: string;
  confidence: "High" | "Medium" | "Low" | string;
}

export interface RiskSignalsResponse {
  risks: RiskSignal[];
  opportunities?: OpportunitySignal[];
}

export interface Recommendation {
  action: string;
  reason: string;
  data_source: string;
  confidence: "High" | "Medium" | "Low" | string;
}

export interface RecommendationsResponse {
  recommendations: Recommendation[];
}

export interface AnomalySignal {
  domain: "Finance" | "Ops" | "HR" | string;
  signal: string;
  zscore: number;
  detail: string;
  data_source: string;
}

export interface AnomaliesResponse {
  anomalies: AnomalySignal[];
}

export interface ArTrendPoint {
  period: string;
  amount: number;
  balance: number;
}

export interface ArTrendsResponse {
  summary: {
    periods: ArTrendPoint[];
  };
  trend?: TrendFlag;
}

export interface HrSummaryResponse {
  salary_total: number;
  overtime_cost_total: number;
  overtime_pct_payroll: number;
  avg_cost_per_employee: number;
  absenteeism_trend: { period: string; hours: number }[];
  absenteeism_trend_flag?: TrendFlag;
}

// Phase 4: Operations / Logistics
export interface OpsKpisExplain {
  fulfillment_days_avg: string;
  downtime_minutes_total: string;
  stock_turnover: string;
  sources: string[];
}

export interface OpsKpis {
  fulfillment_days_avg: number;
  downtime_minutes_total: number;
  stock_turnover: number;
  explain?: OpsKpisExplain;
}

export interface OpsForecastPoint {
  period: string;
  turnover: number;
}

export interface OpsForecast {
  series: OpsForecastPoint[];
  rolling: number[];
  forecast: number[];
}

export interface ProcurementShipment {
  id: string;
  shipment_ref: string;
  supplier_name: string;
  status: "in_transit" | "at_port" | "under_clearance" | "released" | "delivered_to_warehouse";
  expected_arrival_date?: string | null;
  clearance_started_at?: string | null;
  released_at?: string | null;
  currency?: string | null;
  metadata?: Record<string, unknown>;
}

export interface ProcurementDelayShipment {
  shipment_id: string;
  shipment_ref: string;
  supplier_name: string;
  delay_days: number;
  threshold_days: number;
  estimated_impact: number;
  currency: string;
  status: string;
}

export interface SupplierScorecardRow {
  supplier: string;
  shipments: number;
  avg_delay_days: number;
  rejection_rate: number;
  compliance_breach_count: number;
  reliability_score: number;
}

export interface ProcurementAnalysis {
  threshold_days: number;
  delayed_count: number;
  estimated_total_impact: number;
  delayed_shipments: ProcurementDelayShipment[];
  supplier_scorecard: SupplierScorecardRow[];
}
