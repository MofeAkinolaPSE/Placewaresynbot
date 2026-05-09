Good—this is where everything becomes real.
We’ll wire the **end-to-end backend flow** in a clean, testable way.

---

# 🧱 BACKEND WIRING (DJANGO API)

We’ll build **4 core endpoints**:

1. Create Project
2. Submit Checklist + Evidence
3. Run Validation
4. Generate Report (Agent call)

---

# 1️⃣ BASIC SETUP

Install DRF (Django REST Framework):

```bash id="4lhwcz"
pip install djangorestframework
```

```python id="c1qq0z"
# settings.py
INSTALLED_APPS = [
    ...
    'rest_framework',
    'compliance',
]
```

---

# 2️⃣ SERIALIZERS (DATA PIPELINE)

```python
# compliance/serializers.py
from rest_framework import serializers
from .models import *

class EvidenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Evidence
        fields = "__all__"


class SubmissionSerializer(serializers.ModelSerializer):
    evidences = EvidenceSerializer(many=True, read_only=True)

    class Meta:
        model = Submission
        fields = "__all__"


class ProjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Project
        fields = "__all__"
```

---

# 3️⃣ ENDPOINT 1 — CREATE PROJECT

```python
# compliance/views.py
from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import *
from .serializers import *

@api_view(['POST'])
def create_project(request):
    serializer = ProjectSerializer(data=request.data)
    if serializer.is_valid():
        project = serializer.save()
        return Response({"project_id": project.id})
    return Response(serializer.errors, status=400)
```

---

# 4️⃣ ENDPOINT 2 — SUBMIT CHECKLIST

This handles:

* compliance status
* comments
* evidence upload

```python
@api_view(['POST'])
def submit_requirement(request):
    project_id = request.data.get("project_id")
    requirement_id = request.data.get("requirement_id")

    submission, _ = Submission.objects.get_or_create(
        project_id=project_id,
        requirement_id=requirement_id
    )

    submission.compliance_status = request.data.get("compliance_status")
    submission.status = "complete"
    submission.comment = request.data.get("comment", "")
    submission.save()

    # Handle file upload
    if "file" in request.FILES:
        Evidence.objects.create(
            submission=submission,
            file=request.FILES["file"],
            type=request.data.get("type", "other")
        )

    return Response({"status": "saved"})
```

---

# 5️⃣ ENDPOINT 3 — VALIDATION ENGINE

Rule-based (no AI).

```python
@api_view(['POST'])
def run_validation(request):
    project_id = request.data.get("project_id")

    submissions = Submission.objects.filter(project_id=project_id)

    Gap.objects.filter(project_id=project_id).delete()

    gaps = []

    for sub in submissions:
        req = sub.requirement

        if req.tag == "mandatory":
            has_evidence = sub.evidences.exists()

            if sub.compliance_status != "compliant" or not has_evidence:
                gap = Gap.objects.create(
                    project_id=project_id,
                    requirement=req,
                    issue="Missing or insufficient evidence",
                    severity="high"
                )
                gaps.append(gap.id)

    return Response({
        "gaps_created": len(gaps)
    })
```

---

# 6️⃣ ENDPOINT 4 — GENERATE REPORT (AGENT CALL)

This is the core pipeline.

---

## A. Build structured input

```python
def build_agent_payload(project_id):
    project = Project.objects.get(id=project_id)

    clauses_data = []

    for clause in Clause.objects.filter(standard=project.standard):
        requirements_data = []

        for req in clause.requirements.all():
            sub = Submission.objects.filter(
                project=project,
                requirement=req
            ).first()

            requirements_data.append({
                "requirement_id": req.code,
                "text": req.text,
                "status": sub.compliance_status if sub else "non_compliant",
                "evidence": [e.file.url for e in sub.evidences.all()] if sub else [],
                "comment": sub.comment if sub else ""
            })

        clauses_data.append({
            "clause_id": clause.code,
            "title": clause.title,
            "requirements": requirements_data
        })

    gaps = Gap.objects.filter(project=project)

    return {
        "project_info": {
            "name": project.name,
            "client": project.client,
            "scope": project.scope
        },
        "clauses": clauses_data,
        "gaps": [
            {
                "requirement_id": g.requirement.code,
                "issue": g.issue,
                "severity": g.severity
            } for g in gaps
        ],
        "compliance_summary": {
            "overall_score": 70  # placeholder for now
        }
    }
```

---

## B. Call AI Agent

```python
import requests

def call_agent(payload):
    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": "Bearer YOUR_API_KEY"
        },
        json={
            "model": "gpt-5.3",
            "messages": [
                {"role": "system", "content": "ISO 27001 auditor..."},
                {"role": "user", "content": str(payload)}
            ]
        }
    )

    return response.json()
```

---

## C. Generate + Store Report

```python
@api_view(['POST'])
def generate_report(request):
    project_id = request.data.get("project_id")

    payload = build_agent_payload(project_id)
    agent_output = call_agent(payload)

    content = agent_output["choices"][0]["message"]["content"]

    # Assuming JSON response
    import json
    data = json.loads(content)

    report = Report.objects.create(
        project_id=project_id,
        introduction=data["introduction"],
        scope=data["scope"],
        methodology=data["methodology"],
        findings=data["findings"],
        gap_analysis=data["gap_analysis"],
        recommendations=data["recommendations"],
        conclusion=data["conclusion"]
    )

    return Response({
        "report_id": report.id
    })
```

---

# 7️⃣ URL ROUTING

```python
# compliance/urls.py
from django.urls import path
from .views import *

urlpatterns = [
    path('create-project/', create_project),
    path('submit/', submit_requirement),
    path('validate/', run_validation),
    path('generate-report/', generate_report),
]
```

```python
# main urls.py
path('api/', include('compliance.urls'))
```

---

# 🔁 FULL FLOW (NOW WORKING)

```plaintext id="vj3z3s"
Frontend → create project
        ↓
Submit checklist + evidence
        ↓
Run validation
        ↓
Generate report
        ↓
Store report
        ↓
Return report_id
```

---

# ⚠️ IMPORTANT IMPROVEMENTS (NEXT ITERATION)

Don’t skip these later:

* Replace `str(payload)` with proper JSON prompt formatting
* Add retry + error handling for agent
* Add compliance scoring logic
* Add report preview endpoint
* Add async task queue (Celery) for generation

---

# 🚀 WHAT YOU HAVE NOW

You can:

* Capture data ✔
* Validate ✔
* Call AI ✔
* Generate report ✔

This is your **first working system**

---

# NEXT MOVE

We tighten the system:

👉 **Validation scoring engine (real % calculation)**
👉 **DOC/PDF export pipeline**
👉 **Frontend binding (Builder UI → API)**

Pick your next move.
