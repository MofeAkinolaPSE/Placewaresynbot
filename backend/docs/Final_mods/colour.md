Nice — this second dump tells a completely different story than the first brand. If you reused the Premier Care styling here, it would look wrong immediately.

Let’s lock this one properly.

---

# 🎯 🔥 FRONTEND PROMPT — PLACEWARE UI COLOR SYSTEM

## 🧠 0. CORE BRAND IDENTITY (IMPORTANT)

This is **not a purple medical system**.

👉 This brand is:

* **Blue-led (trust + corporate)**
* Supported by **teal/cyan accents**
* With **green for success states**
* And a slightly darker, more “tech/logistics” tone than a hospital UI

---

# 🎨 1. CLEANED COLOR SYSTEM (FROM YOUR DATA)

## 🔵 Primary Brand (Core Identity)

Extracted dominant blues:

* **Primary Blue:** `#2740AE` (rgb: 39, 64, 174)
* **Deep Blue:** `#003A91` (rgb: 0, 58, 145)
* **Support Blue:** `#256CAE` (rgb: 37, 108, 174)

👉 Usage:

* Navigation bar
* Primary buttons
* Active UI states
* Links

---

## 🌊 Secondary Accent (Teal / Cyan Layer)

* **Teal:** `#02646F` (rgb: 2, 100, 111)
* **Cyan:** `#14AAF5` (rgb: 20, 170, 245)

👉 Usage:

* Highlights
* Info states
* Secondary actions
* UI emphasis

---

## 🟢 Success System

* `#62C76A` (rgb: 98, 199, 106)
* `#25D366` (WhatsApp green)

👉 Usage:

* Completed states
* Success indicators

---

## 🟣 Minor Accent (Rare Use)

* `#9B52E1` (rgb: 155, 82, 225)

👉 Use sparingly:

* Notifications
* Tags (not core UI)

---

## ⚪ Neutral System (CRUCIAL)

### Backgrounds

* Main BG: `#F8F9FA`
* Light panels: `#EFEFFD`, `#E8EEFE`
* Cards: `#FFFFFF`

---

### Borders

* `#D6D8DD`
* `#BCC7E7`
* `#CCCCCC`

---

### Text System

* Primary: `#101513`
* Secondary: `#4E4E4E`
* Muted: `#767676`
* Soft: `#999999`

---

# 🧱 2. DESIGN RULES

### This UI should feel:

* Structured
* Slightly technical (not clinical)
* Clean but not sterile
* More “operations dashboard” than “hospital UI”

---

### ❌ Avoid:

* Purple dominance
* Heavy medical styling
* Overly soft UI

---

### ✅ Embrace:

* Blue dominance
* Clear contrast
* Slightly stronger borders
* Functional clarity

---

# 🧩 3. QUEUE SYSTEM COMPONENT MAPPING

## 🧾 Queue Card

* BG: White
* Border: `#D6D8DD`
* Radius: 6–8px
* Shadow: minimal

---

### Status Left Border

| Status     | Color     |
| ---------- | --------- |
| Waiting    | `#BCC7E7` |
| Called     | `#256CAE` |
| In Service | `#2740AE` |
| Completed  | `#62C76A` |
| Skipped    | `#C0392B` |

👉 Note:

* “In Service” = strongest blue (primary state)

---

## 🔘 Buttons

### Primary Button

* BG: `#2740AE`
* Text: White
* Hover: `#003A91`

---

### Secondary Button

* Border: `#256CAE`
* Text: `#256CAE`
* BG: transparent

---

### Accent Button (Optional)

* BG: `#14AAF5`
* Text: White

---

### Success Button

* BG: `#62C76A`
* Text: White

---

# 🧭 4. LAYOUT SYSTEM

## 🔝 Top Navigation

* BG: `#2740AE`
* Text: White
* Clean, slightly bold presence

---

## 📄 Main Layout

* BG: `#F8F9FA`
* Card-based sections
* Slightly tighter spacing than hospital UI

---

## 🧠 5. INFORMATION HIERARCHY

1. Active Queue Item
2. Queue List
3. Action Buttons
4. Metrics (secondary)

---

# ⚡ 6. INTERACTION MODEL

* Fast transitions (150ms)
* Strong hover states (blue shift)
* Clear click feedback

---

# 🏗️ 7. IMPLEMENTATION (CSS TOKENS)

```css
:root {
  --primary: #2740AE;
  --primary-dark: #003A91;
  --secondary: #256CAE;

  --accent: #14AAF5;
  --teal: #02646F;

  --success: #62C76A;
  --danger: #C0392B;

  --bg-main: #F8F9FA;
  --card-bg: #FFFFFF;
  --border: #D6D8DD;

  --text-primary: #101513;
  --text-secondary: #4E4E4E;
}
```

---

# 🧪 8. VISUAL DIFFERENCE (IMPORTANT INSIGHT)

| System       | Feel                      |
| ------------ | ------------------------- |
| Premier Care | Clinical / calm / purple  |
| Placeware    | Operational / tech / blue |

👉 If both systems look similar → design failed.

---

# 🚀 9. SUCCESS CRITERIA

* Blue is dominant
* UI feels like logistics / operations platform
* Stronger contrast than hospital UI
* Clean but slightly more “active”

---

# 🧠 FINAL TAKE

You now have **two distinct UI systems**:

* One = Healthcare (trust, calm, purple-led)
* One = Operations (efficiency, clarity, blue-led)

That separation is what makes your platform adaptable across clients without rebuilding logic — just swapping design tokens.

---

