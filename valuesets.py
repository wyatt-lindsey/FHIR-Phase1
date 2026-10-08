"""
Code sets (value sets) for the Phase 3 guideline:
  SGLT2 inhibitor for adults with type 2 diabetes and chronic kidney disease.

Each concept is a dict of {code system URL: set of codes}. Keeping them in one
file makes every clinical definition reviewable in one place: when a clinician
asks "what counts as CKD?", this file is the answer.

Codes marked (Synthea) were confirmed in Synthea's module source
(metabolic_syndrome/kidney_conditions.json and metabolic_syndrome/medications.json).
Codes marked (real-world) don't appear in Synthea data but are what real EHRs send;
they're here so the logic carries over later.
"""

import json
from pathlib import Path

SNOMED = "http://snomed.info/sct"
ICD10CM = "http://hl7.org/fhir/sid/icd-10-cm"
LOINC = "http://loinc.org"
RXNORM = "http://www.nlm.nih.gov/research/umls/rxnorm"

# --- Diagnoses -------------------------------------------------------------

TYPE2_DIABETES = {
    SNOMED: {
        "44054006",          # Diabetes mellitus type 2 (Synthea)
        # Complications that imply T2D. Decide in criteria.md whether these count.
        "368581000119106",   # Neuropathy due to type 2 diabetes (Synthea)
        "90781000119102",    # Microalbuminuria due to type 2 diabetes (Synthea)
        "157141000119108",   # Proteinuria due to type 2 diabetes (Synthea)
    },
    ICD10CM: {"E11.9", "E11.21", "E11.22", "E11.29", "E11.65"},  # (real-world, partial)
}

TYPE1_DIABETES = {
    SNOMED: {"46635009"},     # Diabetes mellitus type 1
    ICD10CM: {"E10.9"},       # (real-world, partial)
}

CKD = {
    SNOMED: {
        "431855005",          # CKD stage 1 (Synthea)
        "431856006",          # CKD stage 2 (Synthea)
        "433144002",          # CKD stage 3 (Synthea)
        "431857002",          # CKD stage 4 (Synthea)
        "127013003",          # Disorder of kidney due to diabetes mellitus (Synthea)
        "90781000119102",     # Microalbuminuria due to type 2 diabetes (Synthea)
        "157141000119108",    # Proteinuria due to type 2 diabetes (Synthea)
    },
    ICD10CM: {"N18.1", "N18.2", "N18.30", "N18.31", "N18.32", "N18.4", "N18.9",
              "E11.22"},      # (real-world)
}

# End-stage kidney disease / dialysis: excluded from *starting* an SGLT2 inhibitor.
ESKD = {
    SNOMED: {"46177005"},     # End-stage renal disease (Synthea)
    ICD10CM: {"N18.6", "Z99.2"},  # ESRD; dependence on dialysis (real-world)
}

# --- Labs ------------------------------------------------------------------

EGFR = {
    LOINC: {
        "33914-3",   # eGFR, creatinine-based, MDRD (Synthea)
        "62238-1",   # eGFR, creatinine-based, CKD-EPI (real-world)
        "98979-8",   # eGFR, creatinine-based, CKD-EPI 2021 race-free (real-world)
        "48642-3",   # eGFR, MDRD, non-Black (real-world, legacy)
        "48643-1",   # eGFR, MDRD, Black (real-world, legacy)
    }
}

# Urine albumin-to-creatinine ratio (mg/g). Synthea does NOT generate this lab;
# it only produces dipstick urine protein. Real EHRs will have it.
UACR = {
    LOINC: {
        "9318-7",    # Albumin/Creatinine [Mass Ratio] in Urine
        "14959-1",   # Microalbumin/Creatinine [Mass Ratio] in Urine
    }
}

# --- Medications -----------------------------------------------------------

# RxNorm ingredient codes (TTY=IN), confirmed via RxNav.
SGLT2_INGREDIENTS = {
    "1373458": "canagliflozin",
    "1488564": "dapagliflozin",
    "1545653": "empagliflozin",
    "1992672": "ertugliflozin",
    "2627044": "bexagliflozin",
}

# ADA 2026 rec 11.7a: "an SGLT2 inhibitor with demonstrated benefit to reduce
# CKD progression and cardiovascular events". These three have kidney outcome
# trials (CREDENCE, DAPA-CKD, EMPA-KIDNEY). Decision D12 in criteria.md.
SGLT2_DEMONSTRATED_BENEFIT = {
    "1373458": "canagliflozin",
    "1488564": "dapagliflozin",
    "1545653": "empagliflozin",
}


def sglt2_ingredient(codings, display=""):
    """Name the SGLT2 ingredient in a prescription, or None if unknown.
    Checks ingredient codes, then product names (RxNorm product names always
    spell out the ingredient), including names from sglt2_rxnorm.json."""
    texts = [display or ""]
    for c in codings or []:
        if c.get("code") in SGLT2_INGREDIENTS:
            return SGLT2_INGREDIENTS[c["code"]]
        texts += [c.get("display") or "", _EXPANDED_NAMES.get(c.get("code"), "")]
    text = " ".join(texts).lower()
    return next((n for n in SGLT2_INGREDIENTS.values() if n in text), None)


# Prescriptions are coded at the product level (SCD/SBD), not the ingredient.
# This seed list covers Synthea plus a few common products. Run
# build_sglt2_valueset.py to expand it to every product (including
# combination pills like dapagliflozin/metformin) and write sglt2_rxnorm.json.
_SGLT2_SEED = {
    "1373463",   # canagliflozin 100 MG Oral Tablet (Synthea)
    "1488569",   # dapagliflozin 10 MG Oral Tablet
    "1488574",   # dapagliflozin 5 MG Oral Tablet
    "1486977",   # dapagliflozin 10 MG Oral Tablet [Farxiga]
    "1486981",   # dapagliflozin 5 MG Oral Tablet [Farxiga]
}

_EXPANDED = Path(__file__).with_name("sglt2_rxnorm.json")


_EXPANDED_NAMES = {
    "1373463": "canagliflozin 100 MG Oral Tablet",
    "1488569": "dapagliflozin 10 MG Oral Tablet",
    "1488574": "dapagliflozin 5 MG Oral Tablet",
    "1486977": "dapagliflozin 10 MG Oral Tablet [Farxiga]",
    "1486981": "dapagliflozin 5 MG Oral Tablet [Farxiga]",
}


def _load_sglt2():
    codes = set(SGLT2_INGREDIENTS) | _SGLT2_SEED
    if _EXPANDED.exists():
        data = json.loads(_EXPANDED.read_text())
        codes |= set(data["codes"])
        _EXPANDED_NAMES.update(data.get("names", {}))
    return {RXNORM: codes}


SGLT2_INHIBITORS = _load_sglt2()


def in_valueset(codings, valueset):
    """True if any coding ({'system','code'}) is in the value set."""
    for c in codings or []:
        if c.get("code") in valueset.get(c.get("system"), ()):
            return True
    return False
