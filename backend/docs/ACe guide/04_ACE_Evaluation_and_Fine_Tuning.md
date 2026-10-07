# ACE Backend Research — Evaluation, Fine-Tuning & Improvement

## 1. Do not fine-tune first

First improve:
1. source quality,
2. retrieval,
3. tool selection,
4. system instructions,
5. response examples,
6. evaluation.

Fine-tuning should come later if consistent behaviour remains difficult to achieve.

The research consensus is that many agent use cases can be improved with simpler retrieval and in-context examples before introducing additional complexity.

## 2. Build an ACE evaluation set

Create 100–300 representative questions from real client interactions.

Each test case should contain:

- user question,
- expected intent,
- required source/tool,
- expected factual answer,
- acceptable alternatives,
- forbidden assumptions,
- expected response style.

## 3. Score five dimensions

### 1. Correctness
Did ACE give the right answer?

### 2. Groundedness
Can every important factual claim be traced to retrieved/client data?

### 3. Relevance
Did it answer the actual question?

### 4. Directness
Did it provide the answer without unnecessary explanation?

### 5. Tool/retrieval efficiency
Did it use the appropriate source without unnecessary calls?

For agentic systems, latency and tool-call efficiency should also be measured.

## 4. Useful test categories

### Simple lookup
"How many patients are registered?"

### Entity lookup
"What is the balance for customer X?"

### Workflow
"What happens after the patient arrives?"

### Cross-domain
"Show the patient's latest prescription and outstanding bill."

### Ambiguous
"Check John's record."

Expected:
"Which John do you mean?"

### Missing data
"What is the patient's blood group?"

Expected:
"I don't have a blood group recorded for this patient."

### Conflict
Two sources disagree.

Expected:
Surface the discrepancy.

### Calculation
"How much is outstanding after HMO coverage?"

Expected:
Use deterministic calculation.

### Action
"Mark the patient as arrived."

Expected:
Verify permission and required identifier before mutation.

### Out-of-domain
"Who will win the election?"

Expected:
Do not pretend this is a client-system question.

## 5. Conversation-level evaluation

Do not evaluate only single-turn answers.

Test:
User:
"Show me today's outpatient queue."

ACE:
returns queue.

User:
"The third one."

ACE:
understands the third patient from the previous result.

User:
"Has he paid?"

ACE:
uses the selected patient context and checks billing.

This is the type of continuity that makes ACE feel intelligent rather than merely well-prompted.

## 6. Error taxonomy

Log failures as:

RETRIEVAL_FAILURE
- correct answer existed but wasn't retrieved.

TOOL_SELECTION_FAILURE
- wrong tool chosen.

GROUNDING_FAILURE
- unsupported claim.

ENTITY_RESOLUTION_FAILURE
- wrong patient/customer/product.

CONTEXT_FAILURE
- previous conversation state lost.

STYLE_FAILURE
- answer was accurate but unnatural or verbose.

PERMISSION_FAILURE
- attempted action without authorization.

DATA_QUALITY_FAILURE
- source data itself is incomplete or contradictory.

This makes improvement measurable.

## 7. Regression testing

Every ACE prompt, retrieval, schema, or tool change should run the existing evaluation set.

Do not judge improvements from five hand-picked examples.

Track:
- prompt version,
- model,
- retrieval configuration,
- tool version,
- evaluation score,
- latency,
- token usage.

## 8. Recommended improvement loop

Real conversation
→ anonymize/log
→ classify failure
→ add test case
→ fix prompt/retrieval/tool
→ run regression set
→ deploy
→ monitor

This is the practical path to making ACE feel increasingly "made for the system."

