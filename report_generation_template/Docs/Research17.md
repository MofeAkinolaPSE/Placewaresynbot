Got it — this third site is clearly a **corporate consulting / leadership brand**, and the palette confirms a different intent again: more **trust-heavy corporate blue, neutral grays, minimal accent use**.

I’ve cleaned your DevTools dump and reconstructed a **usable design system + frontend agent prompt** below.

---

# 🎯 🔷 FRONTEND AGENT PROMPT — PANORAMIC SYNERGY UI SYSTEM

## 🧠 0. CORE BRAND IDENTITY

This brand is:

* Corporate
* Executive / leadership-focused
* Trust-first
* Minimal accent usage
* Strong blue dominance with muted grayscale structure

👉 Think: **consulting firm, not SaaS product UI**

---

# 🎨 1. CLEANED COLOR SYSTEM (FROM RAW EXTRACTION)

## 🔵 PRIMARY BRAND BLUE (CORE IDENTITY)

Extracted:

* `#002DA8` (rgb: 0, 45, 168)
* `#2A4585` (rgb: 42, 69, 133)
* `#1863DC` (rgb: 24, 99, 220)
* `#1273EB` (rgb: 18, 115, 235)

👉 Interpretation:

* This is a **deep corporate blue system**
* Multiple shades used for hierarchy

### Usage:

* Navigation
* Primary buttons
* Links
* Section headers
* Key highlights

---

## ⚪ NEUTRAL SYSTEM (VERY IMPORTANT)

### Backgrounds

* `#FFFFFF` → base
* `#F4F4F4` → soft section background
* `#EDEDED` → subtle dividers

### Borders

* `#E0E0E0`
* `#E5E7EB`

### Text Colors

* Primary: `#1C1B1B`
* Secondary: `#333333`
* Muted: `#4D4D4D`
* Soft: `#535A5E`

---

## 🟢 SEMANTIC COLORS (MINIMAL USAGE)

* Success: `#008000`
* Warning: (not heavily used)
* Danger: inherited system red (rare)

👉 Important:
This brand does NOT rely on semantic color variety. It is intentionally restrained.

---

## 🧱 2. DESIGN LANGUAGE RULES

### This UI must feel:

* Executive
* Structured
* Editorial
* Calm and authoritative

---

### ❌ Avoid:

* Bright accent colors
* Playful UI elements
* Overuse of green/yellow/red
* Heavy shadows
* Gradient-heavy interfaces

---

### ✅ Embrace:

* Blue dominance
* White space
* Thin borders
* Subtle hover states
* Typography-led hierarchy

---

# 🧩 3. UI COMPONENT SYSTEM (ADAPTED FOR YOUR QUEUE APP)

Even though this is a leadership site, we map it to your queue system cleanly.

---

## 🧾 Queue Card (Executive Style)

* Background: `#FFFFFF`
* Border: `#E5E7EB`
* Radius: 6px
* Shadow: none or ultra-subtle

👉 This is a **flat corporate UI**, not a modern SaaS card.

---

## 🔵 STATUS INDICATORS (SUBTLE SYSTEM)

| Status     | Color                   |
| ---------- | ----------------------- |
| Waiting    | `#4D4D4D`               |
| Called     | `#1863DC`               |
| In Service | `#002DA8`               |
| Completed  | `#008000`               |
| Skipped    | `#C0392B` (minimal use) |

👉 Key insight:
Statuses are **not loud** — they are informational only.

---

## 🔘 BUTTON SYSTEM

### Primary Button

* BG: `#002DA8`
* Text: White
* Hover: `#1863DC`

---

### Secondary Button

* Border: `#2A4585`
* Text: `#2A4585`
* BG: transparent

---

### Minimal Button Style Rule:

Buttons should feel:

> “Corporate tool actions, not app UI controls”

---

# 🧭 4. LAYOUT SYSTEM

## 🔝 Navigation

* BG: `#FFFFFF`
* Text: `#1C1B1B`
* Bottom border: `#E5E7EB`

👉 Very important:
No colored nav bars. This is a **white-top corporate layout**

---

## 📄 MAIN LAYOUT

* Background: `#FFFFFF`
* Sections separated by:

  * spacing
  * light borders
  * subtle gray blocks (`#F4F4F4`)

---

# 🧠 5. TYPOGRAPHY SYSTEM

* Font: System sans-serif (clean corporate feel)
* Weight hierarchy is critical:

### Headings:

* Bold, dark (`#1C1B1B`)

### Body:

* Medium gray (`#333333`)

### Labels:

* Muted (`#4D4D4D`)

👉 Typography is the **primary UI driver**, not color.

---

# 🧩 6. INTERACTION DESIGN

* Hover effects: very subtle blue tint
* Transitions: 120–180ms
* No bounce / no animation-heavy UI
* Focus states: thin blue outline only

---

# 🏥 7. QUEUE SYSTEM UX ALIGNMENT

This brand prioritizes:

* Clarity over speed visuals
* Structured workflow over urgency

So in your queue system:

### Radiographer actions should be:

* Clearly labeled
* Not color-heavy
* Always visible but understated

---

# ⚙️ 8. CSS TOKEN SYSTEM (IMPLEMENTATION READY)

```css id="p9xq2k"
:root {
  --primary: #002DA8;
  --primary-dark: #2A4585;
  --primary-light: #1863DC;

  --bg-main: #FFFFFF;
  --bg-soft: #F4F4F4;

  --border: #E5E7EB;

  --text-primary: #1C1B1B;
  --text-secondary: #333333;
  --text-muted: #4D4D4D;

  --success: #008000;
  --danger: #C0392B;
}
```

---

# 🧪 9. DESIGN VALIDATION RULES

Your UI is correct only if:

✔ It feels like a corporate dashboard
✔ White space is dominant
✔ Blue is used for hierarchy, not decoration
✔ No “app-like” playful elements exist
✔ Everything feels document-grade and structured

---

# 🧠 FINAL INSIGHT (IMPORTANT)

You now have 3 distinct brand systems:

| Brand             | Identity                              |
| ----------------- | ------------------------------------- |
| Premier Care      | Medical + Purple trust system         |
| Placeware         | Operational SaaS + Blue/Teal          |
| Panoramic Synergy | Executive corporate + restrained blue |

---

# 🚀 NEXT STEP (HIGH VALUE)

If you want to scale this properly, I can build you:

### 👉 A Multi-Tenant Design Engine

* One UI codebase
* 3–10 brand themes
* Dynamic CSS token switching
* Per-client UI identity injection

That’s what turns this from:

> “custom UI per client”

into:

> **enterprise-grade configurable ERP system UI layer**
