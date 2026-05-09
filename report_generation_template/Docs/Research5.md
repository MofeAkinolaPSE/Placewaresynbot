Good—this is the backbone. We’ll keep it **clean, relational, and extensible**, so it supports all standards later without redesign.

Below is a **Django-ready schema** (models.py level), aligned with everything we’ve defined.

---

# 🧱 DATABASE SCHEMA (DJANGO MODELS)

## 1️⃣ STANDARD STRUCTURE (Reusable across 27001, 22301, etc.)

```python
from django.db import models

class Standard(models.Model):
    code = models.CharField(max_length=20)  # e.g. ISO27001
    name = models.CharField(max_length=255)

    def __str__(self):
        return self.code
```

---

```python
class Clause(models.Model):
    standard = models.ForeignKey(Standard, on_delete=models.CASCADE, related_name="clauses")
    code = models.CharField(max_length=20)  # e.g. "5.1"
    title = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.standard.code} - {self.code}"
```

---

```python
class Requirement(models.Model):
    TAG_CHOICES = [
        ("mandatory", "Mandatory"),
        ("recommended", "Recommended"),
        ("optional", "Optional"),
    ]

    clause = models.ForeignKey(Clause, on_delete=models.CASCADE, related_name="requirements")
    code = models.CharField(max_length=20)  # e.g. "5.1.1"
    text = models.TextField()
    action = models.TextField(blank=True, null=True)
    expected_evidence = models.TextField(blank=True, null=True)
    tag = models.CharField(max_length=20, choices=TAG_CHOICES)

    def __str__(self):
        return self.code
```

---

# 2️⃣ PROJECT + USER WORKSPACE

```python
class Project(models.Model):
    name = models.CharField(max_length=255)
    client = models.CharField(max_length=255)
    standard = models.ForeignKey(Standard, on_delete=models.CASCADE)
    scope = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name
```

---

# 3️⃣ USER INPUT (CHECKLIST EXECUTION)

```python
class Submission(models.Model):
    STATUS_CHOICES = [
        ("not_started", "Not Started"),
        ("in_progress", "In Progress"),
        ("complete", "Complete"),
    ]

    COMPLIANCE_CHOICES = [
        ("compliant", "Compliant"),
        ("partial", "Partially Compliant"),
        ("non_compliant", "Non-Compliant"),
    ]

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="submissions")
    requirement = models.ForeignKey(Requirement, on_delete=models.CASCADE)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="not_started")
    compliance_status = models.CharField(max_length=20, choices=COMPLIANCE_CHOICES, blank=True, null=True)

    comment = models.TextField(blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("project", "requirement")
```

---

# 4️⃣ EVIDENCE STORAGE

```python
class Evidence(models.Model):
    TYPE_CHOICES = [
        ("policy", "Policy"),
        ("log", "Log"),
        ("certificate", "Certificate"),
        ("report", "Report"),
        ("other", "Other"),
    ]

    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name="evidences")
    file = models.FileField(upload_to="evidence/")
    type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    uploaded_at = models.DateTimeField(auto_now_add=True)
```

---

# 5️⃣ VALIDATION OUTPUT (GAPS)

```python
class Gap(models.Model):
    SEVERITY_CHOICES = [
        ("low", "Low"),
        ("medium", "Medium"),
        ("high", "High"),
    ]

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="gaps")
    requirement = models.ForeignKey(Requirement, on_delete=models.CASCADE)

    issue = models.TextField()
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES)

    created_at = models.DateTimeField(auto_now_add=True)
```

---

# 6️⃣ COMPLIANCE SCORING

```python
class ComplianceScore(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="scores")
    clause = models.ForeignKey(Clause, on_delete=models.CASCADE)

    score = models.FloatField()  # percentage (0–100)

    class Meta:
        unique_together = ("project", "clause")
```

---

# 7️⃣ GENERATED REPORT STORAGE

```python
class Report(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="reports")

    introduction = models.TextField()
    scope = models.TextField()
    methodology = models.TextField()
    findings = models.JSONField()
    gap_analysis = models.JSONField()
    recommendations = models.JSONField()
    conclusion = models.TextField()

    created_at = models.DateTimeField(auto_now_add=True)
    approved = models.BooleanField(default=False)
```

---

# 8️⃣ (OPTIONAL BUT SMART) RAG INGESTION TRACKING

Keep it simple for now:

```python
class KnowledgeChunk(models.Model):
    source_type = models.CharField(max_length=50)  # template / report
    standard = models.ForeignKey(Standard, on_delete=models.CASCADE)

    content = models.TextField()
    embedding_id = models.CharField(max_length=255)  # reference to vector DB

    created_at = models.DateTimeField(auto_now_add=True)
```

---

# 🔑 DESIGN DECISIONS (WHY THIS WORKS)

### 1. Fully normalized

* No duplication
* Easy to scale across standards

---

### 2. Standard-agnostic

* Same schema supports:

  * ISO 27001
  * ISO 22301
  * ISO 9001
  * ISO 20000

---

### 3. Clean separation

* Requirements ≠ Submissions ≠ Evidence
* Keeps logic predictable

---

### 4. AI-ready

* `Report` stores structured output
* Easy to re-ingest into RAG later

---

# ⚠️ WHAT YOU SHOULD DO NEXT (EXECUTION)

### Step 1

* Create Django app: `compliance`

---

### Step 2

* Drop these models into `models.py`

---

### Step 3

```bash
python manage.py makemigrations
python manage.py migrate
```

---

### Step 4

* Use Django admin to:

  * Upload ISO 27001 checklist (Clause + Requirement)

---

# 🚀 WHAT THIS UNLOCKS

Once this is in place, you can:

* Render checklist UI
* Capture user input
* Store evidence
* Run validation
* Feed agent
* Generate report

---

# NEXT MOVE

We now connect:

👉 **Validation Engine → actual logic (code-level rules)**
or
👉 **API layer (endpoints for frontend + agent trigger)**

Pick one and we continue building.
s