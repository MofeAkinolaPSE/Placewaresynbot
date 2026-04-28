Good instinct—this feature can spiral into over-engineering fast if you treat it like a data mining project.

Reality: **you don’t need a “crawler” or heavy AI system to make this valuable.**
You need a **fast, structured, repeatable lead source + light enrichment.**

---

# 🧠 SynBot Leads Finder (Lean Version)

Think of it as:

> “Google Maps + filtering + enrichment + export”

That’s it.

---

# ⚙️ Core Principle

👉 Don’t “search the internet”
👉 **Query structured location data and enhance it**

---

# ✅ MVP Architecture (Clean & Practical)

## 1. Input (Sales Rep)

Simple form:

```json
{
  "location": "Lekki, Lagos",
  "business_type": "Pharmacy",
  "radius": 3000
}
```

---

## 2. Data Source (Your Engine)

Use:

* **Google Places API**

This already gives:

* Business names
* Addresses
* Coordinates
* Ratings
* Sometimes phone numbers

👉 This replaces 80% of the “lead finding problem”

---

## 3. SynBot Leads Agent Flow

### Step 1 — Query Places API

* Nearby Search OR Text Search

---

### Step 2 — Normalize Data

Convert into your format:

```json
{
  "name": "MediCare Pharmacy",
  "address": "Lekki Phase 1",
  "rating": 4.3,
  "place_id": "...",
  "lat": 6.43,
  "lng": 3.48
}
```

---

### Step 3 — Light Enrichment (Optional but powerful)

Don’t overdo this.

Start with:

* Website (if available)
* Phone number
* Category tagging

Optional later:

* Use **SerpAPI** to find:

  * Emails
  * Social pages

---

## 4. Output (What Sales Actually Needs)

### A. List View

* Name
* Address
* Contact
* Rating

### B. Map View

* Pins of all leads

### C. Actions

* Export CSV
* “Add to CRM”
* Mark as contacted

---

# 🚀 What Makes This “Smart” (Without Overbuilding)

Instead of heavy AI, add **simple scoring logic**

---

## Lead Scoring (Rule-Based First)

```json
{
  "lead_score": 75
}
```

Based on:

* Rating (>4.0 = good)
* Has website
* Has phone number
* Location density

---

👉 Later you can upgrade to AI, but don’t start there.

---

# 🧩 System Design (SynBot Style)

```plaintext
[Sales Dashboard]
        ↓
[Leads Agent API]
        ↓
Google Places API
        ↓
[Formatter + Enrichment]
        ↓
[Leads Database (optional cache)]
        ↓
[UI: List + Map + Export]
```

---

# ⚡ Minimal Backend Endpoints

### 1. Search Leads

```http
POST /leads/search
```

---

### 2. Save Lead

```http
POST /leads/save
```

---

### 3. Export

```http
GET /leads/export
```

---

# 🧠 Smart Optimizations (Low Effort, High Impact)

## 1. Cache Results

* Save results per query
* Avoid repeated API costs

---

## 2. Deduplication

* Use `place_id` as unique key

---

## 3. Pagination

* Google returns limited results per call
* Handle next_page_token

---

## 4. Radius Expansion

If few results:
→ auto-expand search radius

---

# ❌ What NOT to Build (Yet)

Avoid:

* ❌ Full web scraping engine
* ❌ AI crawling websites
* ❌ Complex ML lead scoring
* ❌ Email scraping pipelines

These add complexity fast and break reliability.

---

# 🏁 MVP Build Plan

### Day 1–2

* Connect to Places API
* Build `/leads/search`

---

### Day 3–4

* Build UI (list + map)

---

### Day 5

* Add export + save leads

---

👉 That’s a working product already.

---

# 🔥 Phase 2 (When You’re Ready)

Then layer in:

* Email enrichment (SerpAPI)
* CRM sync
* “Similar businesses nearby”
* AI lead prioritization

---

# 🎯 Bottom Line

* You’re not building a search engine
* You’re building a **location intelligence tool**

Keep it:

* API-first
* Structured
* Fast

---
