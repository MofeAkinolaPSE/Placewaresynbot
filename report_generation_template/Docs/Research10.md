Good — this is the layer that makes everything you’ve built **production-grade instead of “script-driven AI”**.

We’re now structuring the backend so it behaves like a **clean, scalable enterprise system**:

* Views stay thin (only HTTP handling)
* Business logic moves into services
* Agents are isolated
* Validation + scoring are reusable modules
* RAG is a pluggable dependency, not hardcoded logic

---

# **API + Service Layer Architecture (Django Services Pattern)**

---

# **1. High-Level Architecture**

We restructure Django into a **3-layer service architecture**

```text id="arch_overview"
API Layer (Views / DRF)
        ↓
Service Layer (Business Logic)
        ↓
Domain Layer (Agents + Validation + RAG + Scoring)
        ↓
Data Layer (Models / DB)
```

---

## Key Principle

> Views should never contain logic.
> Everything important lives in services.

---

# **2. Project Structure (Clean Architecture Layout)**

```text id="folder_structure"
app/
│
├── api/
│   ├── views/
│   ├── serializers/
│   ├── urls.py
│
├── services/
│   ├── report_service.py
│   ├── agent_service.py
│   ├── validation_service.py
│   ├── scoring_service.py
│   ├── export_service.py
│
├── agents/
│   ├── base_agent.py
│   ├── iso27001_agent.py
│   ├── iso9001_agent.py
│   ├── ndpa_agent.py
│
├── rag/
│   ├── context_builder.py
│   ├── retriever.py
│   ├── embeddings.py
│
├── domain/
│   ├── rules.py
│   ├── schemas.py
│
├── models/
│   ├── report.py
│   ├── evidence.py
│   ├── validation.py
│   ├── scoring.py
│
└── utils/
    ├── logger.py
    ├── file_handler.py
```

---

# **3. API Layer (Thin Controllers Only)**

## 3.1 Report Generation Endpoint

```python id="api_generate_report"
class ReportGenerateAPIView(APIView):

    def post(self, request):

        service = ReportService()

        result = service.generate_report(
            user=request.user,
            payload=request.data
        )

        return Response(result)
```

---

## Key Rule:

No AI logic here. No validation. No scoring.

Only orchestration.

---

# **4. Service Layer (CORE BUSINESS LOGIC)**

This is where your system actually “thinks”.

---

# **4.1 Report Service (Orchestrator Service)**

```python id="report_service"
class ReportService:

    def __init__(self):
        self.agent_service = AgentService()
        self.validation_service = ValidationService()
        self.scoring_service = ScoringService()
        self.export_service = ExportService()

    def generate_report(self, user, payload):

        # 1. Create Report DB entry
        report = Report.objects.create(
            user=user,
            title=payload["title"],
            report_type=payload["report_type"],
            status="processing"
        )

        # 2. Run Agent
        agent_output = self.agent_service.run(
            report=report,
            inputs=payload
        )

        # 3. Validate Output
        validation = self.validation_service.validate(
            report,
            agent_output
        )

        # 4. Score Report
        score = self.scoring_service.calculate(
            validation
        )

        # 5. Save Sections
        self._save_sections(report, agent_output)

        # 6. Export (optional async later)
        export_files = self.export_service.generate(report)

        report.status = "completed"
        report.save()

        return {
            "report_id": report.id,
            "validation": validation,
            "score": score,
            "export": export_files
        }
```

---

# **4.2 Agent Service (AI Execution Layer)**

This isolates ALL AI logic.

```python id="agent_service"
class AgentService:

    def run(self, report, inputs):

        # 1. Select Agent
        agent = AgentRouter.route(report.report_type)

        # 2. Build RAG Context
        context = ContextBuilder.build(
            query=inputs.get("scope"),
            report_type=report.report_type
        )

        # 3. Retrieve Evidence
        evidence = Evidence.objects.filter(report=report)

        # 4. Execute Agent
        result = agent.generate(
            inputs=inputs,
            context=context,
            evidence=evidence
        )

        # 5. Log execution
        AgentExecution.objects.create(
            report=report,
            agent_type=report.report_type,
            input_payload=inputs,
            prompt_used=result["prompt"],
            raw_output=result["output"]
        )

        return result["output"]
```

---

# **4.3 Validation Service**

```python id="validation_service"
class ValidationService:

    def validate(self, report, agent_output):

        missing_sections = self._check_sections(report)
        evidence_gaps = self._check_evidence(agent_output)
        consistency_issues = self._check_consistency(agent_output)

        validation = ValidationResult.objects.create(
            report=report,
            missing_sections=missing_sections,
            evidence_gaps=evidence_gaps,
            consistency_issues=consistency_issues,
            is_valid=len(missing_sections) == 0
        )

        return validation
```

---

# **4.4 Scoring Service (Compliance Engine)**

```python id="scoring_service"
class ScoringService:

    def calculate(self, validation):

        section_score = max(0, 100 - len(validation.missing_sections) * 10)
        evidence_score = max(0, 100 - len(validation.evidence_gaps) * 8)
        consistency_score = max(0, 100 - len(validation.consistency_issues) * 12)

        total = (
            section_score * 0.4 +
            evidence_score * 0.35 +
            consistency_score * 0.25
        )

        return ComplianceScore.objects.create(
            report=validation.report,
            section_score=section_score,
            evidence_score=evidence_score,
            consistency_score=consistency_score,
            total_score=round(total, 2),
            status=self._status(total)
        )

    def _status(self, score):
        if score >= 85:
            return "APPROVED"
        elif score >= 60:
            return "APPROVED_WITH_GAPS"
        return "FAILED"
```

---

# **4.5 Export Service (DOCX + PDF Layer)**

```python id="export_service"
class ExportService:

    def generate(self, report):

        docx_path = self._generate_docx(report)
        pdf_path = self._convert_pdf(docx_path)

        return {
            "docx": docx_path,
            "pdf": pdf_path
        }
```

---

# **5. API Layer Expansion (Full Endpoint Map)**

## Core System APIs

```text id="api_map"
POST   /api/reports/generate/        → ReportService
GET    /api/reports/{id}/            → Fetch report
POST   /api/reports/{id}/validate/   → ValidationService
POST   /api/reports/{id}/score/      → ScoringService
POST   /api/reports/{id}/export/     → ExportService
POST   /api/evidence/upload/         → Evidence handling
POST   /api/agents/trigger/          → Direct agent execution
```

---

# **6. Execution Flow (End-to-End System)**

```text id="execution_flow"
1. Frontend sends request
        ↓
2. API Layer receives request
        ↓
3. ReportService orchestrates flow
        ↓
4. AgentService runs AI generation
        ↓
5. RAG Context Builder injects knowledge
        ↓
6. Agent produces report
        ↓
7. ValidationService checks output
        ↓
8. ScoringService calculates compliance %
        ↓
9. ExportService generates files
        ↓
10. Response returned to frontend
```

---

# **7. Why This Architecture Works (Critical Insight)**

## 7.1 Separation of Concerns

* API = communication only
* Services = intelligence orchestration
* Agents = domain reasoning
* RAG = knowledge retrieval
* Models = persistence

---

## 7.2 Scales Cleanly into Microservices

Later you can split:

* agent-service
* rag-service
* validation-service
* export-service

without rewriting logic.

---

## 7.3 Enables AI Observability

You can track:

* prompt versions
* agent outputs
* validation failures
* scoring drift

---

## 7.4 Makes Lovable/Builder UI integration simple

Frontend only calls:

* generate
* view
* export

No complexity leaks.

---

# **8. Recommended Next Step**

Now that backend structure is complete, the next highest-value layer is:

## → Prompt Orchestration System (Versioning + Agent Memory Control)

That’s where we define:

* prompt templates per section
* version control for prompts
* dynamic prompt injection rules
* safe updates without breaking agents

---

If you want, I can take you next into:

> “How prompts become a managed system instead of hardcoded strings”

That’s where most agentic systems actually succeed or fail.
