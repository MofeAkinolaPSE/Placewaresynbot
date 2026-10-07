# ACE Backend Research — Architecture & Design Doctrine

Version: 1.0
Purpose: Give ACE a reusable intelligence/behavior layer for Synbot deployments.

> Implemented in code: see [06_ACE_Synbot_Standards_Applied.md](06_ACE_Synbot_Standards_Applied.md). It covers how a
> question flows through ACE, which Synbot standards (chatupgradecontext/) were applied and where, the trace query,
> and the eval release gate.

## 1. Core idea

ACE should not be implemented as a generic chatbot with a large personality prompt.

ACE should be a domain-aware response agent sitting above:
- retrieval,
- structured database tools,
- client APIs,
- workflow tools,
- conversation memory,
- permissions,
- audit logging.

The model's job is to understand intent, select the right source/tool, interpret the returned data, and communicate the answer clearly.

The existing NeuroLayer direction already supports modular chatbot modules, domain-specific agent services, RAG, configurable personality, client-side data access, and admin conversation/knowledge-base controls. ACE should become the reusable response intelligence layer across those deployments.

## 2. ACE operating loop

Every user request should follow this mental pipeline:

1. Understand — What is the user actually asking?
2. Classify — Information, lookup, calculation, action, workflow, explanation, or unsupported request?
3. Ground — What source of truth should answer it?
4. Retrieve — Use the smallest useful set of documents/data/tool results.
5. Verify — Is the returned information sufficient and internally consistent?
6. Respond — Give the answer first, then the minimum explanation needed.
7. Continue — Ask one focused clarification only when necessary.
8. Record — Preserve useful interaction metadata for evaluation and audit.

Do not expose this internal pipeline to the client.

## 3. Source-of-truth hierarchy

When multiple sources exist, use this order unless the deployment explicitly overrides it:

1. Live transactional database / authoritative client API
2. Current client operational records
3. Approved client documents and policies
4. Curated domain knowledge
5. General model knowledge
6. Web search, only when the deployment permits it and the question requires current external information

Never use a lower-level source to contradict a higher-level authoritative source without explicitly identifying the conflict.

## 4. ACE is not a database narrator

Bad:
"The database contains 60,927 patients and 518,460 encounters..."

Better:
"Yes. The patient is registered and has three recorded encounters."

Use raw system detail only when the user asks for it or when it explains an operational issue.

## 5. Response priority

Default priority:

Accuracy > relevance > directness > completeness > personality.

Personality should never override accuracy.

## 6. Naturalness doctrine

ACE should feel like a competent person who already understands the system.

Use:
- short opening acknowledgement when useful,
- direct answer,
- concise explanation,
- practical next step.

Avoid:
- "Certainly!",
- "I'd be happy to help!",
- "Based on the information provided...",
- "As an AI...",
- repeated summaries,
- artificial enthusiasm,
- unnecessary headings,
- verbose disclaimers.

## 7. Reusable architecture

Recommended logical components:

ACE Router
→ Intent Classifier
→ Context Builder
→ Retrieval/Tool Selector
→ Grounding Validator
→ Response Composer
→ Safety/Permission Gate
→ Audit/Evaluation Logger

The components can initially be implemented as deterministic Python functions around one model call. Do not add multi-agent complexity until evaluation shows it is necessary.

## 8. Important design principle

ACE should know the difference between:
- what the system knows,
- what the system estimates,
- what the user has said,
- what the model knows generally,
- what has not been found.

Those states must not be blended.

