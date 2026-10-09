"""
Hand-built test patients for the SGLT2 / T2D + CKD rule.

Each test is one row of the truth table in criteria.md. When you change a
decision there, change or add a test here first, then change the code.

    python3 -m pytest -q
"""

from datetime import date, timedelta

import pytest

import guideline as g
from guideline import Dx, Lab, PatientData, evaluate
from valuesets import SNOMED, ICD10CM, LOINC, RXNORM

AS_OF = date(2026, 10, 1)


def days_ago(n):
    return AS_OF - timedelta(days=n)


def dx(code, status="active", system=SNOMED, display=None, **kw):
    return Dx(codings=[{"system": system, "code": code}], clinical_status=status,
              verification=kw.pop("verification", "confirmed"), display=display or code, **kw)


T2D = dx("44054006", display="Diabetes mellitus type 2")
CKD3 = dx("433144002", display="CKD stage 3")
METFORMIN = ([{"system": RXNORM, "code": "860975"}], "Metformin ER 500 MG")
CANAGLIFLOZIN = ([{"system": RXNORM, "code": "1373463"}], "canagliflozin 100 MG Oral Tablet")


def patient(age=60, conditions=(T2D, CKD3), egfr=((45, 30),), uacr=(), meds=(METFORMIN,)):
    """egfr/uacr: tuples of (value, days_ago)."""
    return PatientData(
        id="test", name="Test Patient",
        birth_date=None if age is None else date(AS_OF.year - age, 1, 1),
        conditions=list(conditions),
        egfr=[Lab(v, "mL/min/{1.73_m2}", days_ago(d)) for v, d in egfr],
        uacr=[Lab(v, "mg/g", days_ago(d)) for v, d in uacr],
        active_meds=list(meds),
    )


# --- The main path ----------------------------------------------------------

def test_typical_eligible_patient():
    r = evaluate(patient(), AS_OF)
    assert r.status == g.RECOMMEND, r


@pytest.mark.parametrize("egfr,expected", [
    (20.0, g.RECOMMEND),        # boundary: >= 20 qualifies
    (19.9, g.NOT_APPLICABLE),   # just below
    (90.0, g.RECOMMEND),        # normal eGFR but coded CKD (e.g. stage 1 with albuminuria)
])
def test_egfr_threshold(egfr, expected):
    assert evaluate(patient(egfr=((egfr, 10),)), AS_OF).status == expected


# --- Population ---------------------------------------------------------------

def test_deceased_patient_not_applicable():
    # D14: found in hand review (patient 112236 died in 2017; code said INSUFFICIENT_DATA)
    p = patient()
    p.deceased, p.deceased_date = True, days_ago(30)
    r = evaluate(p, AS_OF)
    assert r.status == g.NOT_APPLICABLE and "deceased" in r.reasons[0]


def test_deceased_boolean_without_date_not_applicable():
    p = patient()
    p.deceased = True
    assert evaluate(p, AS_OF).status == g.NOT_APPLICABLE


def test_death_after_as_of_date_is_ignored():
    # Evaluating as of a past date, before the patient died
    p = patient()
    p.deceased, p.deceased_date = True, AS_OF + timedelta(days=10)
    assert evaluate(p, AS_OF).status == g.RECOMMEND



def test_under_18_not_applicable():
    assert evaluate(patient(age=17), AS_OF).status == g.NOT_APPLICABLE


def test_missing_birth_date_is_insufficient():
    assert evaluate(patient(age=None), AS_OF).status == g.INSUFFICIENT_DATA


def test_no_diabetes():
    assert evaluate(patient(conditions=(CKD3,)), AS_OF).status == g.NOT_APPLICABLE


def test_type1_excluded():
    t1 = dx("46635009")
    assert evaluate(patient(conditions=(t1, T2D, CKD3)), AS_OF).status == g.NOT_APPLICABLE


def test_resolved_t2d_does_not_count():
    resolved = dx("44054006", status="resolved")
    assert evaluate(patient(conditions=(resolved, CKD3)), AS_OF).status == g.NOT_APPLICABLE


def test_entered_in_error_does_not_count():
    bad = dx("44054006", verification="entered-in-error")
    assert evaluate(patient(conditions=(bad, CKD3)), AS_OF).status == g.NOT_APPLICABLE


def test_icd10_codes_work_too():
    conds = (dx("E11.9", system=ICD10CM), dx("N18.31", system=ICD10CM))
    assert evaluate(patient(conditions=conds), AS_OF).status == g.RECOMMEND


# --- CKD definition -----------------------------------------------------------

def test_no_ckd_evidence():
    r = evaluate(patient(conditions=(T2D,), egfr=((85, 30),)), AS_OF)
    assert r.status == g.NOT_APPLICABLE and "No evidence of CKD" in r.reasons[0]


def test_ckd_from_two_low_egfrs_90_days_apart():
    r = evaluate(patient(conditions=(T2D,), egfr=((52, 200), (48, 20))), AS_OF)
    assert r.status == g.RECOMMEND, r


def test_single_low_egfr_is_not_ckd():
    # A single low value can be acute kidney injury or a lab blip.
    r = evaluate(patient(conditions=(T2D,), egfr=((48, 20),)), AS_OF)
    assert r.status == g.NOT_APPLICABLE


def test_two_low_egfrs_too_close_together():
    r = evaluate(patient(conditions=(T2D,), egfr=((52, 60), (48, 20))), AS_OF)
    assert r.status == g.NOT_APPLICABLE


def test_ckd_from_albuminuria():
    r = evaluate(patient(conditions=(T2D,), egfr=((75, 15),), uacr=((120, 180), (95, 15))), AS_OF)
    assert r.status == g.RECOMMEND, r


def test_resolved_ckd_without_lab_evidence():
    r = evaluate(patient(conditions=(T2D, dx("433144002", status="resolved")),
                         egfr=((70, 30),)), AS_OF)
    assert r.status == g.NOT_APPLICABLE


# --- Exclusions and data gaps -------------------------------------------------

# D15: several eGFR results on the latest day (found in hand review, patient 220864:
# 54.377 and 16.41 at the same timestamp, and the code picked one arbitrarily)

@pytest.mark.parametrize("order", [((54.377, 0), (16.41, 0)), ((16.41, 0), (54.377, 0))])
def test_same_day_egfr_on_both_sides_of_threshold_is_flagged(order):
    r = evaluate(patient(egfr=((45, 120),) + order), AS_OF)
    assert r.status == g.INSUFFICIENT_DATA
    assert "Conflicting eGFR" in r.reasons[-1]


def test_same_day_egfr_both_above_threshold_uses_lowest():
    r = evaluate(patient(egfr=((48, 5), (31, 5))), AS_OF)
    assert r.status == g.RECOMMEND
    assert r.facts["latest_egfr"][0] == 31


def test_same_day_egfr_both_below_threshold():
    r = evaluate(patient(egfr=((18, 5), (12, 5))), AS_OF)
    assert r.status == g.NOT_APPLICABLE


def test_older_low_result_does_not_count_as_same_day():
    r = evaluate(patient(egfr=((15, 40), (45, 5))), AS_OF)
    assert r.status == g.RECOMMEND


def test_already_on_sglt2():
    r = evaluate(patient(meds=(METFORMIN, CANAGLIFLOZIN)), AS_OF)
    assert r.status == g.NOT_APPLICABLE and "Already on" in r.reasons[0]


def test_already_on_sglt2_without_demonstrated_benefit_is_flagged():
    # D13: ertugliflozin is an SGLT2 inhibitor, but has no kidney outcome trial
    ertu = ([{"system": RXNORM, "code": "1992672"}], "ertugliflozin 5 MG Oral Tablet")
    r = evaluate(patient(meds=(METFORMIN, ertu)), AS_OF)
    assert r.status == g.NOT_APPLICABLE
    assert "no kidney outcome trial" in r.reasons[0]
    assert r.facts["current_sglt2"] == "ertugliflozin"


def test_combination_pill_counts_as_on_sglt2(monkeypatch):
    # dapagliflozin/metformin ER, an SCD code that build_sglt2_valueset.py adds.
    # Simulate that file being present by adding the code for this test.
    xigduo = ([{"system": RXNORM, "code": "1593058",
                "display": "24 HR dapagliflozin 10 MG / metformin hydrochloride 1000 MG Extended Release Oral Tablet"}],
              "24 HR dapagliflozin 10 MG / metformin hydrochloride 1000 MG Extended Release Oral Tablet")
    import valuesets
    monkeypatch.setitem(valuesets.SGLT2_INHIBITORS, RXNORM,
                        valuesets.SGLT2_INHIBITORS[RXNORM] | {"1593058"})
    r = evaluate(patient(meds=(xigduo,)), AS_OF)
    assert r.status == g.NOT_APPLICABLE and "no kidney outcome trial" not in r.reasons[0]


def test_recommendation_names_agents_with_demonstrated_benefit():
    # D12 / ADA 11.7a: "an SGLT2 inhibitor with demonstrated benefit"
    r = evaluate(patient(), AS_OF)
    assert r.facts["suggested_agents"] == ["canagliflozin", "dapagliflozin", "empagliflozin"]
    assert "ertugliflozin" not in " ".join(r.reasons)


def test_eskd_excluded():
    esrd = dx("46177005", display="End-stage renal disease")
    assert evaluate(patient(conditions=(T2D, esrd), egfr=((12, 10),)), AS_OF).status == g.NOT_APPLICABLE


def test_no_egfr_is_insufficient_data():
    assert evaluate(patient(egfr=()), AS_OF).status == g.INSUFFICIENT_DATA


def test_stale_egfr_is_insufficient_data():
    assert evaluate(patient(egfr=((45, 400),)), AS_OF).status == g.INSUFFICIENT_DATA


def test_future_dated_lab_ignored():
    r = evaluate(patient(egfr=((45, 30), (15, -5))), AS_OF)
    assert r.status == g.RECOMMEND


# --- FHIR JSON -> PatientData -------------------------------------------------

def test_build_patient_data_from_fhir_json():
    pat = {"resourceType": "Patient", "id": "p1", "birthDate": "1960-05-01",
           "name": [{"given": ["Lyman173"], "family": "Runte676"}]}
    conds = [
        {"resourceType": "Condition",
         "clinicalStatus": {"coding": [{"code": "active"}]},
         "verificationStatus": {"coding": [{"code": "confirmed"}]},
         "code": {"coding": [{"system": SNOMED, "code": "44054006",
                              "display": "Diabetes mellitus type 2 (disorder)"}]},
         "onsetDateTime": "2010-01-01T00:00:00Z"},
        {"resourceType": "Condition",
         "clinicalStatus": {"coding": [{"code": "active"}]},
         "verificationStatus": {"coding": [{"code": "confirmed"}]},
         "code": {"coding": [{"system": SNOMED, "code": "433144002"}],
                  "text": "Chronic kidney disease stage 3 (disorder)"}},
    ]
    obs = [{"resourceType": "Observation", "status": "final",
            "code": {"coding": [{"system": LOINC, "code": "33914-3"}]},
            "valueQuantity": {"value": 41.2, "unit": "mL/min/{1.73_m2}"},
            "effectiveDateTime": "2026-09-13T10:00:00-04:00"}]
    meds = [
        {"resourceType": "MedicationRequest", "status": "active",
         "medicationCodeableConcept": {"coding": [{"system": RXNORM, "code": "860975",
                                                   "display": "Metformin"}]}},
        {"resourceType": "MedicationRequest", "status": "stopped",
         "medicationCodeableConcept": {"coding": [{"system": RXNORM, "code": "1373463"}]}},
        {"resourceType": "MedicationRequest", "status": "active",
         "medicationReference": {"reference": "Medication/m1"}},
    ]
    med_res = {"Medication/m1": {"resourceType": "Medication", "id": "m1",
                                 "code": {"coding": [{"system": RXNORM, "code": "106892"}],
                                          "text": "Humulin 70/30"}}}

    p = g.build_patient_data(pat, conds, obs, meds, med_res)
    assert p.deceased is False
    dead = g.build_patient_data({**pat, "deceasedDateTime": "2017-03-02T10:00:00-05:00"}, conds, obs, meds, med_res)
    assert dead.deceased and dead.deceased_date == date(2017, 3, 2)
    assert p.name == "Lyman173 Runte676"
    assert p.birth_date == date(1960, 5, 1)
    assert p.egfr[0].value == 41.2 and p.egfr[0].when == date(2026, 9, 13)
    assert [d for _, d in p.active_meds] == ["Metformin", "Humulin 70/30"]  # stopped one dropped
    assert evaluate(p, AS_OF).status == g.RECOMMEND


# --- The fetch layer, against a fake server ----------------------------------

class FakeFhir:
    """Stands in for Fhir so fetch_patient_data can be tested without a server."""
    def __init__(self, pages):
        self.pages = pages

    def get(self, path, **params):
        return self.pages[path]

    def search(self, rtype, **params):
        yield from self.pages[rtype]

    def included(self, rtype, **params):
        return self.pages[rtype], {}


def test_fetch_patient_data_wires_layers_together():
    fake = FakeFhir({
        "Patient/p1": {"id": "p1", "birthDate": "1950-01-01", "name": [{"family": "X"}]},
        "Condition": [{"clinicalStatus": {"coding": [{"code": "active"}]},
                       "code": {"coding": [{"system": SNOMED, "code": "44054006"}]}}],
        "Observation": [],
        "MedicationRequest": [],
    })
    p = g.fetch_patient_data(fake, "p1")
    r = evaluate(p, AS_OF)
    assert r.status == g.NOT_APPLICABLE and "No evidence of CKD" in r.reasons[0]
