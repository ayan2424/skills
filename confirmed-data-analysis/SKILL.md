---
name: confirmed-data-analysis
description: Convert natural-language data-analysis and data-science requests into schema-guided review drafts, explain unfamiliar inputs in plain language, obtain explicit user confirmation, freeze a validated execution contract, run structured analysis, and reconcile computed results with official values. Use for metric trends, dimension comparisons, funnels, retention, growth decomposition, anomaly diagnosis, randomized experiment analysis and significance testing, experiment sample-size or power calculation, propensity score matching (PSM), and synthetic control when users may not know statistical terminology, metric definitions or causal assumptions are ambiguous, confirmation is required before execution, or official totals must be checked. Prefer the generic data-analysis skill when confirmation-first contracting is unnecessary, and prefer stronger domain-specific skills when available.
license: unknown
metadata:
  version: '1.0.0'
---

# Confirmed Data Analysis

Turn an informal analysis request into a traceable contract before running data. When a compatible data-analysis runtime is available, reuse it after confirmation; otherwise use suitable local analysis tools while preserving this Skill's contract and validation rules. Keep this Skill responsible for intent normalization, field provenance, confirmation, contract locking, and official-value reconciliation.

## Non-negotiable gate

Never run SQL, download full data, or produce formal analytical conclusions from a request draft.

- Keep every draft at `execution_allowed = false`.
- Execute only from a user-confirmed contract with `locked = true` and `execution_allowed = true`.
- Treat silence, partial clarification, tentative agreement, and memory hints as non-confirmation.
- If a confirmed field changes, create a new contract version. Never mutate the prior contract silently.
- Allow read-only metadata discovery and small sample previews before confirmation only when needed to map fields. Label them as discovery, not analysis results.

## Workflow

### 1. Capture the request

Preserve the user's exact natural-language request. Detect one primary capability and retain up to three candidates when ambiguous:

- `metric_trend`
- `dimension_compare`
- `funnel`
- `retention`
- `growth_decomposition`
- `anomaly_diagnosis`
- `experiment_analysis`
- `experiment_sample_size`
- `propensity_score_matching`
- `synthetic_control`

If no capability is reliable, set `selected_capability = undetermined` and ask only the question needed to choose it.

Set `interaction_mode = guided` when the user asks for explanations, says they do not understand an input, repeatedly answers “不知道”, or uses an unfamiliar statistical term tentatively. Use `adaptive` by default and `compact` only when the user clearly prefers terse technical interaction.

### 2. Select and read the target schema

Read `references/common.schema.json` and exactly one capability schema:

- `references/metric-trend.schema.json`
- `references/dimension-compare.schema.json`
- `references/funnel.schema.json`
- `references/retention.schema.json`
- `references/growth-decomposition.schema.json`
- `references/anomaly-diagnosis.schema.json`
- `references/experiment-analysis.schema.json`
- `references/experiment-sample-size.schema.json`
- `references/propensity-score-matching.schema.json`
- `references/synthetic-control.schema.json`

Read `references/intake-confirmation-workflow.md` when building or revising a draft. Read `references/official-validation-workflow.md` whenever official values are supplied or requested.
Read `references/causal-experiment-workflow.md` for experiment analysis, sample-size calculation, PSM, synthetic control, or any request for significance or causal interpretation.
Read `references/input-explanation-guide.md` whenever a field is missing, inferred, high-risk, statistically specialized, or the user signals that they do not understand an input.

### 3. Extract fields and discover candidates

Extract the business question, source, metric definition, time range, grain, timezone, dimensions, filters, comparison baseline, capability-specific parameters, output preferences, and official values. For experiments and causal methods, also extract the estimand, assignment or intervention rule, analysis unit, exposure rule, metric distribution, alpha, power or confidence level, sidedness, minimum detectable effect, covariates, and diagnostic thresholds.

Profile source metadata before mapping physical columns. Use an available data-analysis runtime for CSV, Excel, Superset SQL, and structured-source profiling when possible; otherwise inspect the source with suitable read-only local tools. Do not treat a matching column name as proof of business meaning.

For every field, record:

- value and original text
- `status`: `confirmed`, `inferred`, `defaulted`, `missing`, or `conflict`
- `source`: `user_explicit`, `dataset_inferred`, `session_inherited`, `memory_hint`, `product_default`, or `missing`
- confidence from 0 to 1
- evidence and up to three alternatives
- whether it blocks execution or still needs confirmation

For every blocking or specialized field, also record `user_guidance`: a plain-language meaning, why the field matters, one relevant example, answer options when useful, and what to do if the user does not know. Do not expose raw Schema names without translation.

Never invent formulas, entity keys, joins, funnel order, retention semantics, driver relationships, official-value scope, randomization units, exposure rules, causal estimands, covariates, intervention dates, donor pools, or significance thresholds.

### 4. Build and show a request draft

Shape the partial request according to `references/request-draft.schema.json`. Render a confirmation table with:

| 字段 | 初版值 | 这是什么意思 | 为什么需要 | 是否阻塞 | 需要确认 |
|---|---|---|---|---|---|

Show the table before execution. Ask only blocking questions and high-risk semantic questions. Let the user confirm the whole draft or modify individual fields in natural language.

Use progressive explanation:

- Start with the smallest set of fields needed to make progress; do not dump a full statistics glossary.
- Define a term in one plain sentence before offering technical detail.
- Give 2–3 concrete answer choices when they are truly mutually exclusive, plus allow “不知道”.
- If the user says “不知道”, inspect metadata or experiment configuration when safe. Suggest a default only for low-risk fields and label it as a suggestion. Keep high-risk fields blocked until discovered or explicitly chosen.
- Before confirmation, summarize the practical meaning of the selected settings, such as “这会回答被分流人群的平均影响，未实际看到功能的人也保留在实验组”.

Use the deterministic helper when a draft JSON artifact exists:

```bash
python3 scripts/contract_gate.py render-draft --input request-draft.json
python3 scripts/contract_gate.py check-draft --input request-draft.json
```

### 5. Freeze the confirmed contract

Accept explicit confirmation such as “确认”, “按这个跑”, or “没问题，开始” only for the currently displayed draft version. Promote the draft after resolving every blocking field:

```bash
python3 scripts/contract_gate.py promote \
  --draft request-draft.json \
  --confirmation-text "确认，按这个跑" \
  --output confirmed-analysis-contract.json
```

The helper validates the selected capability schema, the confirmation gate, and the final contract without third-party Python packages. Treat any validation error as blocking.

### 6. Execute through the structured-analysis runtime

After promotion succeeds, pass only `confirmed_request` to the selected analysis runtime. Prefer an installed specialized data-analysis Skill and its existing entrypoints when available instead of recreating file readers, Superset clients, profiling, cleaning, query, export, or handoff logic. When no compatible runtime is installed, use suitable local tools and keep the same contract, provenance, validation, and reporting requirements.

Preserve the confirmed metric definitions, filters, time scope, entity keys, source roles, and official values. If runtime discovery contradicts the contract, stop and return to draft revision rather than silently adapting the query.

For deterministic binary-proportion tests and binary or continuous sample-size calculations, prefer `scripts/experiment_stats.py`. For row-level estimation, use a scientific runtime and record package versions, random seeds, model specifications, exclusions, and diagnostics.

Do not use statistical significance as a synonym for business importance or causality. Report effect size and confidence interval before p-value. Block strong causal interpretation when SRM fails, treatment assignment is unclear, post-treatment covariates enter PSM, overlap or balance is inadequate, synthetic-control pre-fit is poor, or placebo evidence is unavailable.

Use the runtime's `direct`, `assist`, and `escalate` modes. A confirmed contract authorizes execution but does not override comparability, safety, or escalation checks.

### 7. Reconcile official values

After computation and before strong interpretation:

1. Match metric definition, aggregation, deduplication, unit, scope, time range, filters, and timezone.
2. Compare only when definitions are sufficiently comparable.
3. Report computed and official values side by side.
4. Never replace computed results with official values.
5. Apply user-provided tolerances before product defaults.
6. Diagnose large gaps before stating business conclusions.

Return `passed`, `warning`, `critical`, `partial`, or `incomparable` according to `references/official-validation-workflow.md`. If no official value is provided, return `not_requested`.

### 8. Return the output contract

Shape the final result according to `references/output-contract.schema.json`. Separate evidence, result tables, validation, official-value comparison, interpretation, limitations, next actions, and handoff state.

## Blocking rules

Block contract promotion when any of these is true:

- a target-schema required field is missing
- a field is marked `missing`, `conflict`, or `blocking = true`
- a required inferred field has confidence below 0.6
- a high-risk semantic field remains unconfirmed
- a join key or source grain is unverified
- the selected capability is `undetermined`
- the target schema does not match the selected capability
- the official value cannot be scoped well enough to decide comparability
- an experiment lacks a confirmed assignment unit, treatment/control definition, exposure rule, metric denominator, analysis window, or estimand
- a sample-size request lacks baseline level and MDE for binary metrics, or standard deviation and MDE for continuous metrics
- PSM lacks a defensible pre-treatment covariate set, treatment timing, overlap policy, balance threshold, or outcome window
- synthetic control lacks a treated unit, donor pool, intervention date, pre-period, post-period, and outcome definition

Memory may suggest aliases or preferences, but `memory_hint` never counts as confirmation and never lowers the runtime risk mode.

## Validation and maintenance

Validate bundled schemas and the Skill package after changes:

```bash
python3 scripts/contract_gate.py validate-schemas
python3 scripts/experiment_stats.py self-test
python3 /path/to/skill-creator/scripts/quick_validate.py .
```

Read schemas only as needed. Keep detailed protocol in references rather than expanding this file.
