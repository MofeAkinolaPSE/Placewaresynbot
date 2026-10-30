/**
 * The welcome tour: a working day in each ACE role, in the order the work happens (guide section 6).
 *
 * Shown once, on a person's first sign-in (replay: Take the tour again in the user menu, or Show me how). Each step
 * opens its page behind the card and says what to press there, naming controls exactly as on screen. "Show me how"
 * (walkthroughs.ts) then explains every tab and button of that page in detail. Ask ACE's APP_GUIDE
 * (backend/src/services/app_guide.py) describes the same flows - keep the three in step.
 *
 * Checked by day-tours.spec.ts: every role on User Access has a day, every step opens a page that role can open.
 */
import { foldRole } from "./nav-access";

export type DayStep = {
  /** What this part of the day is, e.g. "Register a walk-in". */
  title: string;
  /** The page the step opens (a ?tab= is allowed). */
  href: string;
  /** One or two sentences: when in the day and why. */
  body: string;
  /** What to press there, exact on-screen names. */
  points?: string[];
};

const WELCOME = (who: string): DayStep => ({
  title: "Welcome to ACE",
  href: "/workspace",
  body: `ACE is Placeware's one system: orders, stock and quality, the books, customers and people. This short tour follows a typical day ${who} and opens each page as it goes - you can try things on the real screen while you read.`,
  points: [
    "Next and Back move through the tour; it opens each page for you.",
    "Skip tour if you would rather explore - Take the tour again is in the menu under your name.",
    "Every page has Show me how at the top: a step-by-step guide to every tab and button on it.",
  ],
});

const WORKSPACE: DayStep = {
  title: "Your own day: My Workspace",
  href: "/workspace",
  body: "Start here every morning. My Day shows what is due, requests from colleagues and the work for your role; the work clock records your hours for HR.",
  points: [
    "Start work when you arrive, Break and Resume, End work when you leave (also in the top bar).",
    "Add a task by typing a sentence; Ask sends a colleague a request; Message opens a conversation.",
    "The bell in the top bar is your inbox: requests, mentions and alerts.",
  ],
};

const HELP: DayStep = {
  title: "Help is always one click away",
  href: "/synbot",
  body: "Ask ACE anything about the system in plain words - \"how do I record a receipt with WHT?\" or \"where do I void an invoice?\" - and it answers with the exact clicks. Show me how plays a guided walkthrough on any page.",
  points: [
    "Ask ACE: in the menu, or the round chat button at the bottom right of every page.",
    "Show me how: the button at the top of every page - a tour of that page's tabs and buttons, and walkthroughs that follow an order, a batch or a recall start to finish.",
    "Take the tour again: the ⋮ menu next to your name at the bottom of the side menu.",
  ],
};

const DAYS: Record<string, DayStep[]> = {
  frontdesk: [
    WELCOME("on the Frontdesk"),
    {
      title: "Start of day: Today's queue",
      href: "/frontdesk",
      body: "Today's queue is the Frontdesk's home: every visit and the stage it is at. It updates by itself when QC, Finance or anyone else changes an invoice.",
      points: [
        "Cards: Walk-ins Today, Invoices Raised, Revenue Today, Pending QC, Pending Finance, Completed.",
        "Click a visit in the queue to open its invoice; Show voided brings back voided visits.",
      ],
    },
    {
      title: "Register a walk-in customer",
      href: "/frontdesk",
      body: "The New walk-in tab takes a customer from the door to an invoice: their details, then the items, then delivery and discount, then the invoice details.",
      points: [
        "Search first - a returning customer has their history and details already.",
        "Items: Product, Qty, Unit price; Batch number, Manufacture and Expiry dates fill from Maintain.",
        "Delivery charge (₦) and Discount allowed (₦); then Bill to, Ship to, Customer PO, Payment terms, Ship via.",
        "Create Invoice & Send for QC: the stock is held for this customer so it is not sold twice.",
      ],
    },
    {
      title: "Follow each order: QC, then Finance, then dispatch",
      href: "/frontdesk",
      body: "Every invoice goes QC → Finance → Dispatch, each step done by its own role. The person who raised an invoice cannot QC it. Finance approving it posts it to ACE Books.",
      points: ["Open a visit to see its stage; Print invoice is at the top of its panel.", "Pending QC and Pending Finance count everything still waiting, whatever day it was raised."],
    },
    {
      title: "Change or void before Finance approves",
      href: "/frontdesk/invoices",
      body: "All invoices lists every Frontdesk invoice. Until Finance approves one you can change or void it yourself; after that Finance makes the change in ACE Books.",
      points: [
        "Modify invoice (with a reason): add, remove or change items, delivery charge, discount. If QC had already checked it, it goes back to QC.",
        "Void invoice: until Finance approves it. Voided invoices leave the totals.",
      ],
    },
    {
      title: "End of day: the Activity report",
      href: "/frontdesk",
      body: "The Reports tab gives the day's activity: visits, invoices and revenue, ready to print or send.",
      points: ["Reports tab → Activity report."],
    },
    WORKSPACE,
    HELP,
  ],

  sales: [
    WELCOME("in Sales"),
    {
      title: "Your customers",
      href: "/crm/customers",
      body: "Every customer with their ACE Books sales, balance and reorder cycle. The filters tell you who to call today.",
      points: ["Filters: Buying, At risk, Due to reorder, Owes past due, Lapsing, Lapsed, Never bought.", "Click a customer to open their full panel."],
    },
    {
      title: "A customer's full picture",
      href: "/crm/customers",
      body: "The customer panel brings together what they buy, their invoices and their account, and is where you log every conversation.",
      points: ["Tabs: Sales, What they buy, Invoices, Account, Contact & deals.", "Log call/visit, Reminder, New deal, New request."],
    },
    {
      title: "Raise an order for a customer",
      href: "/customers/workspace",
      body: "Make new request raises an invoice for a customer. It follows the same route as a walk-in: QC → Finance → Dispatch.",
      points: ["Make new request → items → delivery charge and discount → invoice details → Raise Request.", "After Raise Request the panel shows the new invoice with Print invoice."],
    },
    {
      title: "Work the pipeline",
      href: "/crm/sales",
      body: "Deals move New → Qualified → Proposal → Won or Lost. A deal is marked Won by itself when the customer's invoice posts.",
      points: ["Tabs: Pipeline, Reminders, Weekly report, Targets, Leaderboard.", "Message customers sends one message to many."],
    },
    {
      title: "Find new customers",
      href: "/crm/lead-finder",
      body: "Leads & Prospecting finds pharmacies and hospitals near you (GPS) or in an area, so you can call them and add them to the pipeline.",
      points: ["Find prospects → call → Add to pipeline.", "Worked prospects and Website enquiries are their own tabs."],
    },
    { title: "Walk-ins at the Frontdesk", href: "/frontdesk", body: "Sales can serve walk-ins too: the New walk-in tab works exactly as for the Frontdesk team.", points: ["New walk-in → Create Invoice & Send for QC."] },
    WORKSPACE,
    HELP,
  ],

  finance: [
    WELCOME("in Finance"),
    {
      title: "Finance Control Tower",
      href: "/finance/books",
      body: "ACE Books' front page: revenue and profit by month, cash and bank, what customers owe and what we owe, and what needs attention. Sage stays the record up to the hand-over date; ACE Books keeps the books from the next day.",
      points: ["Needs attention lists what to deal with first.", "Every figure opens the records behind it."],
    },
    {
      title: "Approve Frontdesk invoices",
      href: "/frontdesk",
      body: "Orders wait for you in Pending Finance once QC has checked them. Approve posts the invoice to ACE Books: goods to sales, delivery charge to Other Income 40800, discount to Sales Discount 49000.",
      points: ["A customer over their credit limit is blocked until you override with a reason.", "Reject sends it back with your reason."],
    },
    {
      title: "The Invoice register",
      href: "/finance/books/sales?tab=register",
      body: "Every invoice - Sage's, ACE Books' and Frontdesk's (awaiting QC or Finance) - in one list. Open one to see its lines, batches, payments and journal.",
      points: ["In an invoice: Add items, Return / remove items, Record receipt, Print invoice.", "Void only while nothing has been paid on it."],
    },
    {
      title: "Record a customer receipt",
      href: "/finance/books/sales?tab=receipts",
      body: "Record customer receipt applies money received to the invoices it pays. The WHT drop-down works out withholding tax and the amount into the bank.",
      points: ["Full payment or Part payment; WHT: 2%, 3%, 5%, 10% or Other amount.", "A wrong receipt: open it → Correct this receipt."],
    },
    {
      title: "Supplier bills and payments",
      href: "/finance/books/purchases",
      body: "Deliveries QC has received wait under \"Received, waiting on the supplier's bill\". Record the bill (lines are filled) and Post bill; then Pay supplier.",
      points: ["Record supplier bill, Pay supplier, Return to supplier.", "One-off payment pays someone who is not a supplier."],
    },
    {
      title: "Chase overdue customers",
      href: "/finance/ar",
      body: "Credit Control & Alerts: who owes what and for how long, alert rules that warn you, and each customer's credit risk.",
      points: ["Tabs: AR Aging, Alert Rules, P&L Report, Cash Flow, Payroll, Credit Risk.", "Credit limits are set on CRM → Customers → Edit."],
    },
    { title: "Banking", href: "/finance/books/banking", body: "Bank and cash accounts, cash vouchers (petty cash) and bank reconciliation.", points: ["Tabs: Accounts, Vouchers, Reconciliation.", "Transfer between accounts; Import bank statement."] },
    {
      title: "Month end",
      href: "/finance/books/close",
      body: "Reconcile the banks, check the controls, read the statements, then close the period so it cannot change. Management can reopen it.",
      points: ["Tabs: Periods & year end, Data issues, Integrity monitor, Frontdesk postings, Exceptions, Audit trail."],
    },
    {
      title: "Bring ACE up to date from Sage",
      href: "/finance/sage-import",
      body: "While Sage is still in use, load Sage's reports as of a date: Check shows what will change, nothing happens until you confirm.",
      points: ["Into ACE Books → Bring ACE up to date from Sage → Check → confirm.", "Export to Sage makes files the accountant imports into Sage."],
    },
    { title: "Executive Overview", href: "/executive", body: "The company on one page - revenue, profit, cash, ageing, stock, quality, people - with the Needs your attention list." },
    WORKSPACE,
    HELP,
  ],

  quality_assurance: [
    WELCOME("in Quality"),
    {
      title: "Your day starts in My Day",
      href: "/workspace",
      body: "My Day's \"For your role\" lists batches to release, deviations, audits, maintenance, recalls and expired stock. Take it assigns an item to you.",
      points: ["Start work when you arrive; End work when you leave.", "Take it on an item makes it yours."],
    },
    {
      title: "QC check of Frontdesk invoices",
      href: "/quality-control",
      body: "Invoices raised at the Frontdesk wait in the Release queue for QC. You sign with your own login; the person who raised an invoice cannot QC it.",
      points: ["Pass QC sends it on to Finance; Fail QC sends it back with your reason.", "Your name and the date print on the invoice."],
    },
    {
      title: "Incoming batches: Confirm arrived, then Release or Reject",
      href: "/quality-control",
      body: "When goods arrive, Confirm arrived records the supplier, their invoice number, quantity, unit cost, batch number on the pack and dates. The batch is held (QUARANTINED) until you decide.",
      points: ["Release makes it sellable (oldest unexpired first).", "Reject keeps it held and raises a deviation.", "Finance then records the supplier's bill."],
    },
    { title: "Expiry", href: "/quality-control", body: "Every product's lots by expiry. Expired lots can never be sold.", points: ["Expiry tab: quarantine, release, write off or recall a lot."] },
    {
      title: "Recalls",
      href: "/quality-control",
      body: "Open a recall from a batch or from a customer's invoice: the batch is frozen and every customer who bought it is listed. Record what comes back, then close the recall.",
      points: ["Recalls tab → open → trace customers → record returns → close."],
    },
    { title: "Temperature", href: "/quality-control", body: "Cold-chain readings for the stores.", points: ["Temperature tab → New temperature reading."] },
    {
      title: "Compliance & QMS",
      href: "/compliance",
      body: "Audits, Deviations & CAPA, Maintenance, SOPs and Documents. The compliance score is 100 minus deductions for what is overdue.",
      points: ["Overdue items reduce the score and show in My Day and the Executive Overview."],
    },
    { title: "Logistics Calendar", href: "/calendar", body: "Everything due - deliveries, incoming batches, recalls, audits, maintenance, deviations. Dragging an item reschedules the record itself." },
    HELP,
  ],

  ops: [
    WELCOME("in Operations"),
    { title: "Operations overview", href: "/operations", body: "Inventory, logistics and procurement at a glance, including import shipments.", points: ["Procurement tab: import shipments - Mark at port, under clearance, released, delivered to warehouse."] },
    {
      title: "Stock orders",
      href: "/operations/purchase-orders",
      body: "The Reorder plan shows what to buy; stock orders go requested → approved → ordered → received (received when the supplier's bill posts in ACE Books).",
      points: ["Tabs: Reorder plan, Stock orders, Supplier invoices."],
    },
    {
      title: "Deliveries and riders",
      href: "/operations/logistics",
      body: "Logistics Monitor: every delivery, the riders and the live map. Customers get a tracking link; riders sign in on the rider app.",
      points: ["New delivery, assign a rider; Riders; Live map."],
    },
    { title: "Project controls", href: "/operations/project-controls", body: "Active projects, the stage board, their deliveries and stock orders.", points: ["Create new project."] },
    { title: "Suppliers", href: "/operations/suppliers", body: "What we owe each supplier, what we buy from them and how often - read from ACE Books.", points: ["Bought from in the last 12 months / We owe / All; Add supplier."] },
    { title: "Stock levels", href: "/inventory", body: "The live stock workspace: what is low, expiring or dead, and reorders already on the way.", points: ["Request reorder opens Register an incoming batch."] },
    { title: "What is due", href: "/calendar", body: "Deliveries, incoming batches, audits and maintenance on one calendar; drag to reschedule." },
    WORKSPACE,
    HELP,
  ],

  procurement: [
    WELCOME("in Procurement"),
    { title: "The Reorder plan", href: "/operations/purchase-orders", body: "What needs ordering now, what to order soon, expiry risks and slow movers - worked out from sales and stock.", points: ["Reorder plan tab: needs ordering, order soon, expiry risk, healthy, no recent sales."] },
    {
      title: "Raise, approve and order",
      href: "/operations/purchase-orders",
      body: "A stock order is raised, approved, then marked ordered with the supplier and the expected date. It is received when Finance posts the supplier's bill.",
      points: ["Stock orders tab: requested, approved, with supplier, received, cancelled."],
    },
    { title: "Register the incoming batch", href: "/inventory", body: "Request reorder opens Register an incoming batch: supplier first, their invoice number, item, quantity, expected arrival. QC confirms it when it arrives.", points: ["The batch number can wait until the goods arrive."] },
    { title: "Suppliers", href: "/operations/suppliers", body: "What we owe, what we buy and how often, per supplier." },
    WORKSPACE,
    HELP,
  ],

  hr: [
    WELCOME("in HR"),
    { title: "Who is in today", href: "/hr", body: "The HR overview shows who has started work, who is on a break and the hours so far." },
    { title: "Staff directory", href: "/hr", body: "A profile for everyone with a login - created on User Access, completed here (name, title, phone, contracted hours)." },
    { title: "Timesheets", href: "/hr", body: "Hours come from the work clock. Approve, reject or adjust them, add missing hours, export CSV." },
    { title: "Escalation rules", href: "/workspace", body: "Overdue work escalates to the right person by the escalation rules, set from My Workspace (Customise)." },
    HELP,
  ],

  management: [
    WELCOME("for management"),
    { title: "Executive Overview", href: "/executive", body: "The whole company on one page: revenue and profit, cash, ageing, stock, sales trend, customers, quality, people, and the Needs your attention list." },
    {
      title: "How an order becomes cash",
      href: "/frontdesk",
      body: "Frontdesk raises the invoice (stock held) → QC checks it → Finance approves and it posts to ACE Books → dispatch delivers → Finance records the receipt.",
      points: ["Today's queue shows each order's stage live."],
    },
    { title: "The books", href: "/finance/books", body: "Finance Control Tower: ACE Books' revenue, profit, cash and what needs attention. Every figure opens the records behind it." },
    { title: "Who owes us", href: "/finance/ar", body: "Aged receivables, alert rules and each customer's credit risk." },
    { title: "Customers and sales", href: "/crm", body: "Customers, the sales pipeline, targets and the leaderboard." },
    { title: "Stock and quality", href: "/quality", body: "What needs attention now and in the next 14 days: recalls, deliveries, incoming batches, audits, maintenance, deviations, expiry." },
    { title: "Buying stock", href: "/operations/purchase-orders", body: "The reorder plan and stock orders; management can approve." },
    { title: "Deliveries", href: "/operations/logistics", body: "Every delivery, its rider and the live map." },
    { title: "People", href: "/hr", body: "Who is in, the staff directory and timesheets." },
    { title: "What is due", href: "/calendar", body: "Everything scheduled across the company, on one calendar." },
    { title: "Reports", href: "/reports/new", body: "Generate a written report on any record - a recall, an audit, a customer - review what ACE gathered, then download it." },
    { title: "Ask ACE and the Agent Stack", href: "/agents", body: "The Agent Stack runs ACE's analysis agents on demand; Ask ACE answers questions about the business and the system." },
    HELP,
  ],

  viewer: [
    WELCOME("in ACE"),
    WORKSPACE,
    { title: "The Dashboard", href: "/", body: "The ACE Workstation: department tabs and quick actions for what you can see." },
    HELP,
  ],
};

// Admin: the management day, then the admin-only pages.
DAYS.admin = [
  ...DAYS.management.filter((s) => s !== HELP),
  {
    title: "User Access",
    href: "/admin/users",
    body: "Create a login for each person and tick their roles - the preview shows the menu they will get. Edit access takes effect at once; Deactivate or Delete removes access.",
    points: ["Create User → roles → Save.", "Preview onboarding shows any role's welcome tour and walkthroughs."],
  },
  { title: "Workflow", href: "/workflow", body: "Pending approvals and the audit trail of who did what." },
  { title: "Data Intelligence", href: "/admin/data-intelligence", body: "Explore the data behind ACE: field coverage, relationships between records, table classification." },
  { title: "Settings and Data Backup", href: "/settings", body: "System settings, and Data Backup: schedule (Daily / Weekly / Monthly), Back up now, and Save to this computer onto the external drive.", points: ["A reminder shows at the top of every page until a prepared backup is saved."] },
  HELP,
];

export function getDayTour(role: string): DayStep[] | undefined {
  return DAYS[foldRole(role)];
}

/** Every role that has a day (checked against User Access's role list in day-tours.spec.ts). */
export const DAY_ROLES = Object.keys(DAYS);
