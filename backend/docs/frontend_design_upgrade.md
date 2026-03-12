Perfect. This is the level of intentional design direction that prevents frontend drift.

Below is the **unified master prompt** you’ll give to your Frontend Design Agent.
Its job is not to “add components.” Its job is to **transform the entire application into a cohesive, modern, investor-grade interface** using the elements you provided.

This prompt enforces:

* Global visual consistency
* No dead white backgrounds
* Unified motion system
* Unified elevation system
* Unified color logic
* Unified card, table, dashboard, and menu language
* Enterprise-grade polish

---

# 🎯 MASTER FRONTEND REDESIGN DIRECTIVE

*(Give this to the FE Design Agent as-is)*

---

## Objective

Upgrade the entire frontend to a **modern, high-impact, shareholder-grade interface**.

This is not a component addition task.
This is a **system-wide design transformation**.

Every visual element must be upgraded:

* Dashboards
* Charts
* Tables
* Cards
* Buttons
* Menus
* Dropdowns
* Tooltips
* Calendars
* Alerts
* Backgrounds
* Navigation
* Forms
* Layout containers

No page may remain visually flat or default.

Consistency is mandatory.

---

# 1️⃣ Core Design Philosophy

We are building a:

> Fluid, data-rich, executive-grade SaaS interface with motion depth and atmospheric backgrounds.

Design must feel:

* Alive
* Dimensional
* Structured
* Intentional
* Premium

No static white canvas pages with floating cards.
All backend elements need the respective/responsive UI frontend elements.


---

# 2️⃣ Global Visual System (Mandatory Across All Pages)

## A. Background System (No Plain White Pages)

Every page must use one of the following:

### Primary Background Pattern

```tsx
bg-gradient-to-br 
from-background 
via-muted/40 
to-background
```

Add subtle overlay texture:

```tsx
before:absolute before:inset-0 
before:bg-[radial-gradient(circle_at_20%_20%,rgba(0,0,0,0.04),transparent_40%)]
before:pointer-events-none
```

Optional motion depth (for dashboards):

* Low opacity animated gradient mesh
* Very subtle floating blur or grain layer
* Never distracting

Background must:

* Provide depth
* Create contrast
* Frame content
* Never overpower content

---

## B. Elevation & Surface System

All surfaces follow 3-tier elevation:

### Level 1 – Base Surface

* `bg-muted/40`
* soft border
* no heavy shadow

### Level 2 – Interactive Cards

* `bg-background/70`
* `backdrop-blur-md`
* `shadow-xl shadow-black/5`
* `border border-border/50`
* rounded-2xl

### Level 3 – Floating Elements (dropdowns, tooltips, menus)

* `bg-background/80`
* `backdrop-blur-lg`
* `shadow-2xl`
* animated entry

No inconsistent shadow usage allowed.

---

# 3️⃣ Motion System (Unify All Animations)

We standardize on:

* `framer-motion`
* Spring animations
* Soft cubic easing

### Motion Rules:

* Hover: slight scale 1.02–1.05
* Tap: scale 0.97
* Dropdown open: blur → scale → fade
* Cards load: fade + y offset
* No sudden pop-ins

All components must follow one motion language.

---

# 4️⃣ Component Upgrade Strategy

We integrate and standardize the following:

### ✅ Animated Tooltip

Used for:

* User clusters
* Assigned teams
* Ownership visuals

Enhance:

* Glassmorphic background
* Subtle glow gradient under name
* Consistent border radius (rounded-xl minimum)

---

### ✅ Alert Badge

Upgrade:

* Replace flat red/green/blue
* Use gradient variants:

  * error → red → rose
  * success → emerald → teal
  * info → blue → indigo
* Add glow ring on hover
* Add slight pulse for active alerts

Used in:

* System status
* Incidents
* Connectivity
* Notification counts

---

### ✅ Fullscreen Calendar

Upgrade to:

* Elevated container surface
* Softer grid borders
* Hover highlight glow
* Event cards use glass background
* Selected day uses primary gradient fill

Calendar must feel:
Modern. Executive. Spacious.

Not default UI kit.

---

### ✅ Dropdown Menu (Animated)

Standardize:

* Remove raw hard-coded bg-[#111]
* Replace with design system variables
* Add blur
* Add border-border/40
* Add soft glow on hover item
* Add micro-scale on tap

All dropdowns across the app must use this style.

---

### ✅ Fluid Circular Menu

Re-skin:

* Use design token colors
* Add soft neon ring highlight when expanded
* Animate items with slight stagger
* Use consistent surface background

Used for:

* Quick actions
* Floating command triggers
* Context actions

---

# 5️⃣ Button System Consolidation

You currently have duplicate button variants (originui + shadcn).

Unify into ONE button system.

Primary Button:

* Gradient primary background
* Subtle shine hover
* Elevated shadow

Outline Button:

* Transparent glass
* Border glow on hover

Ghost Button:

* Subtle hover background

Icon Buttons:

* Circular
* Elevated
* Micro shadow

No mixed radius. Standardize:

* Default radius: rounded-xl
* Large containers: rounded-2xl

---

# 6️⃣ Dashboard Layout Rules

Every dashboard must:

* Use grid layout
* 2xl rounded cards
* Data cards include:

  * metric
  * subtext
  * trend indicator
  * optional sparkline
* Charts must be framed in elevated containers
* No chart directly on background

Cards must never float on white.

---

# 7️⃣ Table Modernization

All tables must be:

* Wrapped in glass container
* Rounded-2xl
* Header slightly darker surface
* Row hover highlight with soft glow
* Subtle dividing borders
* Sticky header optional

Optional:

* Row-level animated hover reveal actions
* Status badges styled with AlertBadge system

---

# 8️⃣ Chart Container Styling

Every chart must:

* Live inside elevated card
* Have padding
* Have subtle inner shadow
* Optional blurred background gradient behind chart

No raw chart on blank page.

---

# 9️⃣ Typography System

Establish hierarchy:

Page Title:

* text-2xl / text-3xl
* font-semibold
* gradient text optional

Section Title:

* text-lg
* text-muted-foreground

Metric Numbers:

* text-3xl or larger
* font-bold
* tighter tracking

No inconsistent sizes.

---

# 🔟 Layout Consistency Rules

* Standard page padding: p-6 or p-8
* Standard section spacing: gap-6
* Card internal padding: p-6
* No random spacing values
* No mixed radius sizes

Everything follows scale.

---

# 11️⃣ Folder Structure Enforcement

All reusable UI elements must live in:

```
/components/ui
```

If missing:

* Initialize shadcn properly
* Ensure Tailwind configured
* Ensure TypeScript strict mode enabled

No component sprawl across random folders.

---

# 12️⃣ Dark Mode Readiness

All elements must:

* Support dark mode
* Use design tokens (bg-background, bg-muted, etc.)
* Avoid hard-coded colors

No raw hex backgrounds allowed.

---

# 13️⃣ Final Requirement

This is complete ONLY IF:

* No page has plain white background
* All surfaces use elevation system
* All interactive elements follow motion system
* Buttons are unified
* Dropdowns are unified
* Charts are framed
* Tables are modernized
* Calendar is elevated
* Tooltips are glass
* Fluid menu matches theme
* Alert badges are gradient-enhanced
* Typography is consistent

No partial implementation.

This is a full visual system upgrade.

---

# 🚀 What This Achieves

* Investor-grade polish
* Cohesive brand identity
* Motion-driven UI
* Premium SaaS feel
* Scalable design system
* Eliminates UI fragmentation

---

If you want, next step we can:

* Define a **Design Token Layer (colors, radii, shadows, gradients, animation presets)** so this becomes enforceable at the config level instead of manual styling.


Perfect. Below is a **lean, scalable Design Token Spec** for **Synbot AI by Neurolayer** — optimized for:

* ⚡ Fast implementation (Tailwind + CSS variables)
* 🧩 Component consistency
* 🎬 Motion clarity (Framer Motion ready)
* 📈 Future scaling (multi-agent platform growth)

No fluff. Just structure you can ship.

---

# 🧠 Synbot AI — Design Token System (v1)

---

## 1️⃣ Color System (Semantic First)

### Philosophy

* Dark-first AI platform
* Depth via layered neutrals
* Accent = intelligence + energy
* No pure white backgrounds

---

## 🎨 Core Palette (CSS Variables)

```css
:root {
  /* Background Layers */
  --bg-0: #0B0F14;      /* App base */
  --bg-1: #11161D;      /* Section */
  --bg-2: #161C24;      /* Card */
  --bg-3: #1C2430;      /* Elevated */
  
  /* Glass Surface */
  --glass-bg: rgba(255, 255, 255, 0.04);
  --glass-border: rgba(255, 255, 255, 0.08);

  /* Primary Accent (AI Blue) */
  --accent-500: #3B82F6;
  --accent-600: #2563EB;
  --accent-700: #1D4ED8;

  /* Secondary Accent (Neural Purple) */
  --secondary-500: #8B5CF6;

  /* Success / Warning / Error */
  --success-500: #22C55E;
  --warning-500: #F59E0B;
  --error-500: #EF4444;

  /* Text */
  --text-primary: #E6EDF3;
  --text-secondary: #9CA3AF;
  --text-muted: #6B7280;

  /* Border */
  --border-subtle: rgba(255,255,255,0.06);
}
```

---

## 🌈 Gradient Tokens

Used for:

* Agent cards
* CTA buttons
* Hero backgrounds
* Active states

```css
--gradient-primary: linear-gradient(135deg, #3B82F6 0%, #8B5CF6 100%);
--gradient-soft: linear-gradient(135deg, rgba(59,130,246,0.15), rgba(139,92,246,0.15));
--gradient-hero: radial-gradient(circle at 20% 20%, rgba(59,130,246,0.25), transparent 40%);
```

Rule:

* Never stack more than 2 gradients.
* Gradients = meaning, not decoration.

---

# 2️⃣ Elevation System (Depth Language)

Synbot is an AI system → depth implies intelligence layers.

### Shadow Tokens

```css
--shadow-sm: 0 2px 6px rgba(0,0,0,0.25);
--shadow-md: 0 6px 18px rgba(0,0,0,0.35);
--shadow-lg: 0 12px 32px rgba(0,0,0,0.45);
--shadow-glow: 0 0 20px rgba(59,130,246,0.25);
```

### Elevation Map

| Layer | Usage                    |
| ----- | ------------------------ |
| bg-0  | App shell                |
| bg-1  | Sections                 |
| bg-2  | Cards                    |
| bg-3  | Active / Hover           |
| Glass | Modal / overlay surfaces |

---

# 3️⃣ Spacing System (Predictable Rhythm)

8px base scale.

| Token | Value |
| ----- | ----- |
| xs    | 4px   |
| sm    | 8px   |
| md    | 16px  |
| lg    | 24px  |
| xl    | 32px  |
| 2xl   | 48px  |
| 3xl   | 64px  |

Rule:

* Avoid arbitrary values.
* Vertical spacing > horizontal spacing for readability.

---

# 4️⃣ Typography System

### Font Stack

* Primary: Inter
* Fallback: system-ui

### Scale

| Token     | Size | Usage         |
| --------- | ---- | ------------- |
| text-xs   | 12px | Meta          |
| text-sm   | 14px | Secondary     |
| text-base | 16px | Default       |
| text-lg   | 18px | Emphasis      |
| text-xl   | 20px | Section title |
| text-2xl  | 24px | Page title    |
| text-3xl  | 30px | Hero          |

Rules:

* No more than 4 sizes per screen.
* Titles = 600 weight.
* Body = 400/500.

---

# 5️⃣ Motion System (Framer Motion Ready)

AI UI must feel responsive but controlled.

### Duration Tokens

| Token  | ms    |
| ------ | ----- |
| fast   | 120ms |
| normal | 200ms |
| slow   | 300ms |

### Easing

```js
const easeStandard = [0.4, 0, 0.2, 1];
```

### Motion Rules

| Interaction  | Motion                 |
| ------------ | ---------------------- |
| Hover card   | scale 1 → 1.02         |
| Modal open   | opacity 0 → 1 + y 8px  |
| Agent select | subtle glow + bg shift |
| Page change  | fade + 16px slide      |

No bounce. No elastic. AI ≠ playful SaaS.

---

# 6️⃣ Component Tokens

---

## 🟦 Button System

Primary:

* Background: gradient-primary
* Text: white
* Shadow: shadow-md
* Hover: brightness 1.05

Secondary:

* bg-2
* border-subtle
* hover bg-3

Ghost:

* transparent
* hover bg-2

---

## 🟪 Card (Agent Card Spec)

```css
background: var(--bg-2);
border: 1px solid var(--border-subtle);
border-radius: 16px;
padding: 24px;
transition: 200ms easeStandard;
```

Hover:

* bg-3
* shadow-md
* subtle gradient overlay

---

## 🟫 Modal / Glass Panel

```css
background: var(--glass-bg);
backdrop-filter: blur(12px);
border: 1px solid var(--glass-border);
border-radius: 20px;
```

---

# 7️⃣ Interaction States

| State    | Rule               |
| -------- | ------------------ |
| Hover    | 2% scale max       |
| Focus    | 2px accent outline |
| Active   | bg-3 shift         |
| Disabled | 50% opacity        |

---

# 8️⃣ Tailwind Integration (Efficient Setup)

Add to `tailwind.config.js`:

```js
theme: {
  extend: {
    colors: {
      bg0: 'var(--bg-0)',
      bg1: 'var(--bg-1)',
      accent: 'var(--accent-500)',
    },
    boxShadow: {
      glow: 'var(--shadow-glow)',
    },
  }
}
```

---

# 9️⃣ Scalability Layer (Future-Proofing Synbot)

When Synbot expands:

* Agent-specific accent colors (mapped to semantic tokens)
* Light mode variant (invert neutral system only)
* Role-based theme overrides (enterprise dashboards)
* Dynamic gradient shifts per AI domain

---

# 🚀 Implementation Roadmap (Lean Stack)

Phase 1:

* CSS variables
* Tailwind integration
* Core components (Button, Card, Modal)

Phase 2:

* Motion presets
* Gradient overlays
* Agent card animations

Phase 3:

* Theming system (agent categories)
* Design audit automation (lint tokens usage)

---

# Final Verdict

This token system gives Synbot AI:

* Visual intelligence
* System-level consistency
* Component scalability
* Clear brand authority
* Clean low-code implementation

If you'd like next:
I can generate a **production-ready Tailwind theme file** or a **React component starter kit aligned to this token system**.
