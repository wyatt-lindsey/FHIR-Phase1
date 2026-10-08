# Criteria: SGLT2 inhibitor for adults with type 2 diabetes and CKD

Status: DRAFT (not yet reviewed by a clinician)
Owner: Wyatt Lindsey
Last updated: 2026-10-08

## Source

- **Guideline:** ADA Standards of Care in Diabetes—2026, Section 11 (Chronic Kidney Disease and Risk Management), subsection "Direct Kidney Effects of Glucose-Lowering Medications". Supporting source: KDIGO 2022 Clinical Practice Guideline for Diabetes Management in CKD.
- **Recommendation:** 11.7a, evidence grade **A**
- **Exact text:**

  > 11.7a For people with type 2 diabetes and CKD, use of a sodium–glucose cotransporter 2 (SGLT2) inhibitor with demonstrated benefit to reduce CKD progression and cardiovascular events is recommended. SGLT2 inhibitors should be initiated in individuals with eGFR ≥20 mL/min/1.73 m2 but can safely continue until kidney failure.

- **Supporting text from the same subsection:** SGLT2 inhibitors slow GFR loss "through mechanisms that appear independent of glycemia," and "kidney beneficial effects should be considered when selecting agents for glucose lowering."

### What the text settles, and what it leaves open

| Phrase in 11.7a | What it means for the code |
| --- | --- |
| "people with type 2 diabetes and CKD" | Population: T2D **and** CKD. No age, A1c, or CKD stage is named, so D1, D3 and D5 are still our decisions |
| "an SGLT2 inhibitor with demonstrated benefit" | Not every drug in the class qualifies. See D12 |
| "should be initiated in individuals with eGFR ≥20" | Starting threshold is ≥ 20, inclusive. Confirms D7 |
| "can safely continue until kidney failure" | Stopping is a different rule from starting. Patients already on the drug are out of scope for this rule (D8). Kidney failure is the end point, which supports the ESKD exclusion (D9) |
| Grade A | Strongest evidence level, from randomized trials |
| Glycemia-independent mechanism | The rule must not depend on A1c (no A1c check in `evaluate()`) |

### Out of scope for this rule

**11.7b** (a GLP-1 receptor agonist with demonstrated benefit for people with T2D and CKD, grade A) is a separate recommendation. It's a good candidate for the second rule, since it reuses the same population logic (D1–D6) with a different drug class. Don't fold it into this one. Keeping one recommendation per rule keeps every suggestion traceable to one sentence.

## Decisions

Each row is one ambiguity in the sentence above and how the code resolves it. Change a decision here first, then update the tests, then the code.

| # | Question | Decision | Why | Code |
| --- | --- | --- | --- | --- |
| D1 | Who counts as an adult? | Age 18 or older on the evaluation date | 11.7a names no age. Pediatric use is a separate question with its own evidence | `MIN_AGE` |
| D2 | What counts as type 2 diabetes? | Active, non-refuted Condition in `TYPE2_DIABETES`, including T2D complication codes | Synthea codes T2D complications separately | `valuesets.TYPE2_DIABETES` |
| D3 | Does a high A1c without a diagnosis count? | No (for now) | Keeps the first version simple. Revisit with a clinician. A1c plays no other role, because the benefit is independent of glycemia | — |
| D4 | What if type 1 diabetes is also coded? | Not applicable | 11.7a is for T2D. Conflicting codes need human review | `TYPE1_DIABETES` |
| D5 | What counts as CKD? | Any one of: (a) an active CKD diagnosis; (b) eGFR below 60 on 2 results at least 90 days apart in the last 2 years; (c) UACR of 30 mg/g or more on 2 results at least 90 days apart | 11.7a doesn't define CKD. KDIGO defines it as abnormal for more than 3 months. Diagnoses are often missing from real problem lists | `CKD`, `persistent()` |
| D6 | How recent must the eGFR be? | Within 365 days | Kidney function changes. A stale value can't support a decision about starting a drug | `EGFR_LOOKBACK_DAYS` |
| D7 | What eGFR is needed to start? | Latest eGFR **≥ 20** (20.0 qualifies, 19.9 doesn't) | 11.7a: "should be initiated in individuals with eGFR ≥20" | `EGFR_INITIATION_MIN` |
| D8 | What about patients already on an SGLT2 inhibitor? | Not applicable to this rule, whatever their eGFR | 11.7a separates starting (≥ 20) from continuing ("until kidney failure"). This rule only answers "should this patient start?" A continuation rule would be a separate rule | `SGLT2_INHIBITORS` |
| D9 | Exclusions? | End-stage kidney disease or dialysis | 11.7a says the drugs continue "until kidney failure," so kidney failure is outside the recommendation | `ESKD` |
| D10 | Missing data? | Return INSUFFICIENT_DATA, not "no" | "We don't know" is different from "not eligible," and a clinician should see that | `evaluate()` |
| D11 | Other contraindications (pregnancy, recurrent ketoacidosis, allergy)? | _Open — ask a clinician_ | 11.7a doesn't list them | |
| D12 | Which SGLT2 inhibitors have "demonstrated benefit to reduce CKD progression and cardiovascular events"? | Canagliflozin, dapagliflozin and empagliflozin. A RECOMMEND result names these three | Each has a dedicated kidney outcome trial (CREDENCE, DAPA-CKD and EMPA-KIDNEY). Ertugliflozin and bexagliflozin have no kidney outcome trial. **Confirm with a clinician** | `SGLT2_DEMONSTRATED_BENEFIT` |
| D13 | Does "already on an SGLT2 inhibitor" (D8) include one *without* demonstrated benefit (ertugliflozin, bexagliflozin)? | Yes, still not applicable, but the reason says the agent lacks kidney outcome evidence so a clinician can decide whether to switch | Suggesting a second drug from the same class would be wrong. Silently treating ertugliflozin as equal would hide what 11.7a says | `evaluate()` |

## Truth table (hand-checked)

Fill this in from the cohort run (Step 6 in the guide). Pick some patients the code marks RECOMMEND and some it doesn't, read their full record, and record what you conclude yourself before you look at the code's answer.

| Patient ID | Name | My answer | Code's answer | Agree? | Notes |
| --- | --- | --- | --- | --- | --- |
| | | | | | |

## Open questions for clinical review

- [ ] Is D5 (the CKD definition) acceptable? Should a single very low eGFR count?
- [ ] Should D3 change (count patients with a high A1c but no T2D diagnosis)?
- [ ] Which contraindications belong in D11?
- [ ] D12: Is the list of agents with demonstrated benefit right, and should it change as new trials report?
- [ ] D13: For a patient on ertugliflozin or bexagliflozin, should the tool suggest switching?
- [ ] Should there be a separate continuation rule (on an SGLT2 inhibitor, eGFR below 20, not on dialysis)? What would it tell the clinician?
- [ ] Should 11.7b (GLP-1 receptor agonist) be the next rule?
