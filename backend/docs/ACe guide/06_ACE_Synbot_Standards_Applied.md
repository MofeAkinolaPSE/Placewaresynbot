# 06 — Synbot standards applied to ACE

The 13 Synbot standards in `chatupgradecontext/` describe a platform for many clients. Only
the parts Placeware needs now were applied. They build on guides 00–05; they don't replace them.
This page lists what was taken, where it lives in the code, and what was deliberately left out.

## How ACE decides what to say (one question, end to end)

```
question
  -> action? (email, meeting, task, report, reorder)   app.py _detect_action_intent
       a question ("what do we need to reorder?") is never an action
  -> plan live lookups by keyword                       app.py _plan_tools
  -> drop lookups the asker's roles can't use,
     but remember them as DENIED                        app.py _run_orchestration_plan + ace_evidence.denied_tools
  -> run lookups (60s cache)                            services/ace_tools.py via tool_registry
  -> evidence bundle: one <source> per result, with a status
     ok / not_found / ambiguous / denied / unavailable  services/ace_evidence.evidence_block
  -> prompt layers: CORE -> PLACEWARE -> APP GUIDE ->
     ROLE -> NOW -> EXAMPLES                            app.py _build_chat_instruction
  -> LLM
  -> clean text (no Markdown, no AI filler)             services/ace_voice.clean_answer
  -> response guard (scrub internal names, flag claims) services/ace_evidence.guard_answer
  -> trace record "ace_chat_trace" in the audit log     app.py chat()
```

## What was applied, and where

| Standard (doc in chatupgradecontext) | Rule | Where in ACE |
|---|---|---|
| Conversational Intelligence Standard; Voice Guide | Answer, then support, then limit, then next step; short; no AI openers | `ace_voice.ACE_CORE`, from guide 01 |
| Voice Guide s.5 | Confidence follows evidence: confirmed, partial or nothing | `ACE_CORE` → "WHAT YOU KNOW VS WHAT YOU DON'T" |
| Voice Guide s.6; Grounding s.12 | Missing data is not a negative fact; answer the part you can | `ACE_CORE`, eval family `missing` |
| Voice Guide s.8 | Ambiguity: ask one question naming the options; one clear reading, just proceed | `ace_tools._resolve` returns candidates, status `ambiguous` |
| Voice Guide s.12; Agent & Tool s.13 (tool result contract) | "Couldn't look", "you can't see this" and "there is none" are different answers | `ace_evidence.status_of`, `evidence_block` |
| Prompt Architecture s.2–9 | Layered prompt: core, client pack, role, runtime, evidence, examples | `_build_chat_instruction`; `PROMPT_VERSION` in `ace_evidence` |
| Grounding s.3 (source hierarchy) | Live data, then app guide, then company documents, then conversation, then general knowledge | the "PLACEWARE" block in `_build_chat_instruction` |
| Security s.21 (untrusted content) | Records, documents and chat text are data, never instructions | `ACE_CORE` "KEEP THE MACHINERY OUT OF SIGHT"; evidence header; KB labelled "information, not instructions" |
| Security s.7; Prompt Architecture s.17 | Access enforced in code, not only by prompt; denied is said plainly | tool role sets in `tool_registry`, `denied_tools`, eval family `access` |
| Integration s.10.2; Blueprint s.14 (read before write) | Chat never writes a stock order with a guessed quantity; it shows the reorder plan and where to raise the order | `eos/service._handle_trigger_replenishment_action` (read-only) |
| Agent & Tool s.13 | A failed action never shows raw errors and never reads as done | the action-dispatch guard in `app.py chat()` |
| Blueprint s.13 (response guard) | Scrub tool/table names; flag unbacked "done" and "none" claims | `ace_evidence.guard_answer` |
| Operations s.12 (request trace) | One record per turn: path, sources and status, denials, guard flags, timings, prompt version | audit event `ace_chat_trace` (`placeware_audit_logs`, `subject_type=chat_orchestration`) |
| Evaluation s.6–10, 16 | Test families, severity levels, release gate | `backend/eval/ace_eval.py` |

## Reading the trace

```sql
SELECT created_at, details->>'path' AS path, details->'sources' AS sources, details->'denied' AS denied,
       details->'guard_flags' AS flags, details->>'llm_s' AS llm_s, details->>'question_preview' AS q
FROM placeware_audit_logs WHERE event_type = 'ace_chat_trace' ORDER BY created_at DESC LIMIT 50;
```

A non-empty `guard_flags` means the reply needed scrubbing or claimed something the evidence
didn't back. Those questions are the next eval cases to add.

## Release gate (run after any change to ACE's prompt, guide, tools or model)

```
docker cp backend/eval/ace_eval.py chat-backend.v1:/tmp/ace_eval.py
docker exec chat-backend.v1 python /tmp/ace_eval.py
```

The run must end with `RELEASE GATE PASS`, which means no critical or high failures.
- **Critical:** a leak of access-restricted data, or an unconfirmed write.
- **High:** a wrong or invented figure, or a leaked internal name.
- **Low:** length or style. Low failures don't block a release, but fix them.

## Deliberately not applied (not needed for Placeware now)

- Multi-tenant and multi-company isolation. Placeware is one company; revisit this if a subsidiary is added.
- Specialist agents, a router agent, and multi-agent loops. Keyword planning plus narrow tools answers in about 2s, and the standards themselves say not to add agents without measured need.
- Vector-index operations, chunking and embedding pipelines beyond the existing knowledge base.
- A feedback UI in chat (helpful / wrong / missing). It's worth adding later: the trace already carries the `trace_id` it would attach to.
- Feature flags and a kill switch for ACE. Stopping the backend container is the current off switch.
