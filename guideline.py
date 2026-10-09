"""
Phase 3: encode one guideline recommendation as code.

  ADA Standards of Care in Diabetes-2026, recommendation 11.7a (grade A):
    "For people with type 2 diabetes and CKD, use of a sodium-glucose
    cotransporter 2 (SGLT2) inhibitor with demonstrated benefit to reduce CKD
    progression and cardiovascular events is recommended. SGLT2 inhibitors
    should be initiated in individuals with eGFR >=20 mL/min/1.73 m2 but can
    safely continue until kidney failure."

  This rule answers one question: should this patient START an SGLT2
  inhibitor? Continuing one is a different rule (criteria.md, D8).

The file has three layers, kept separate on purpose:

  1. fetch_patient_data()  -- talks to a FHIR server (I/O)
  2. build_patient_data()  -- turns raw FHIR JSON into a small PatientData object
  3. evaluate()            -- pure logic: PatientData + date -> Result

Only layer 3 encodes the guideline, and it never touches the network, so you can
test it with hand-built patients. In Phase 4, CDS Hooks will hand you the FHIR
resources directly ("prefetch"), and you'll reuse layers 2 and 3 unchanged.

Usage:
    python3 guideline.py --base http://localhost:8080/fhir
    python3 guideline.py --base http://localhost:8080/fhir --patient PATIENT_ID
    python3 guideline.py --base http://localhost:8080/fhir --csv cohort.csv
"""

import argparse
import csv
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import requests

import valuesets as vs

# --- Thresholds. Every number here is a decision recorded in criteria.md. -----

MIN_AGE = 18
EGFR_INITIATION_MIN = 20          # mL/min/1.73m2; 11.7a: "initiated ... eGFR >=20"
EGFR_LOOKBACK_DAYS = 365          # latest eGFR must be this recent
CKD_EGFR_MAX = 60                 # eGFR below this suggests CKD...
UACR_CKD_MIN = 30                 # ...or UACR (mg/g) at or above this...
CKD_PERSIST_DAYS = 90             # ...on two results at least this far apart
CKD_LAB_LOOKBACK_DAYS = 730       # only consider lab evidence from the last 2 years

ACTIVE_STATUSES = {"active", "recurrence", "relapse"}
BAD_VERIFICATION = {"refuted", "entered-in-error"}

SUGGESTED_AGENTS = sorted(vs.SGLT2_DEMONSTRATED_BENEFIT.values())   # D12

RECOMMEND = "RECOMMEND"
NOT_APPLICABLE = "NOT_APPLICABLE"
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


# --- Data model ---------------------------------------------------------------

@dataclass
class Lab:
    value: float
    unit: str
    when: date


@dataclass
class Dx:
    codings: list
    clinical_status: str      # active / resolved / inactive / ...
    verification: str         # confirmed / refuted / entered-in-error / ...
    onset: date | None = None
    abatement: date | None = None
    display: str = ""


@dataclass
class PatientData:
    id: str
    name: str
    birth_date: date | None
    conditions: list = field(default_factory=list)   # [Dx]
    egfr: list = field(default_factory=list)         # [Lab]
    uacr: list = field(default_factory=list)         # [Lab]
    active_meds: list = field(default_factory=list)  # [(codings, display)]
    deceased: bool = False                           # deceasedBoolean or deceasedDateTime present
    deceased_date: date | None = None                # deceasedDateTime, if given


@dataclass
class Result:
    status: str
    reasons: list
    facts: dict

    def __str__(self):
        return f"{self.status}: " + "; ".join(self.reasons)


# --- Layer 3: the guideline logic (pure) ---------------------------------------

def age_on(birth, on):
    return on.year - birth.year - ((on.month, on.day) < (birth.month, birth.day))


def has_active(conditions, valueset, as_of):
    """Return the first Condition in the value set that is active on as_of."""
    for c in conditions:
        if c.verification in BAD_VERIFICATION:
            continue
        if c.clinical_status not in ACTIVE_STATUSES:
            continue
        if c.abatement and c.abatement <= as_of:
            continue
        if c.onset and c.onset > as_of:
            continue
        if vs.in_valueset(c.codings, valueset):
            return c
    return None


def persistent(labs, test, as_of, lookback_days, apart_days):
    """True if two results in the lookback window pass `test` and are at
    least `apart_days` apart (KDIGO: abnormal for more than 3 months)."""
    since = as_of - timedelta(days=lookback_days)
    hits = sorted(l.when for l in labs if since <= l.when <= as_of and test(l.value))
    return bool(hits) and (hits[-1] - hits[0]).days >= apart_days


def latest(labs, as_of):
    past = [l for l in labs if l.when <= as_of]
    return max(past, key=lambda l: l.when) if past else None


def latest_day(labs, as_of):
    """All results from the most recent day on or before as_of (D15).
    Real and Synthea records can hold several results for the same day."""
    e = latest(labs, as_of)
    return [l for l in labs if l.when == e.when] if e else []


def evaluate(p: PatientData, as_of: date) -> Result:
    facts = {}

    # 0. Alive (D14). A death dated after as_of doesn't count, so evaluating
    #    a past date (--as-of) still works for patients who died later.
    if p.deceased and (p.deceased_date is None or p.deceased_date <= as_of):
        when = f" on {p.deceased_date}" if p.deceased_date else ""
        return Result(NOT_APPLICABLE, [f"Patient deceased{when}"], facts)

    # 1. Adult
    if p.birth_date is None:
        return Result(INSUFFICIENT_DATA, ["No birth date"], facts)
    facts["age"] = age_on(p.birth_date, as_of)
    if facts["age"] < MIN_AGE:
        return Result(NOT_APPLICABLE, [f"Age {facts['age']} < {MIN_AGE}"], facts)

    # 2. Type 2 diabetes (and not type 1)
    if has_active(p.conditions, vs.TYPE1_DIABETES, as_of):
        return Result(NOT_APPLICABLE, ["Has type 1 diabetes"], facts)
    t2d = has_active(p.conditions, vs.TYPE2_DIABETES, as_of)
    if not t2d:
        return Result(NOT_APPLICABLE, ["No active type 2 diabetes"], facts)
    facts["t2d"] = t2d.display

    # 3. Exclusions
    eskd = has_active(p.conditions, vs.ESKD, as_of)
    if eskd:
        return Result(NOT_APPLICABLE, [f"End-stage kidney disease / dialysis ({eskd.display})"], facts)
    on_sglt2 = [(codings, d) for codings, d in p.active_meds
                if vs.in_valueset(codings, vs.SGLT2_INHIBITORS)]
    if on_sglt2:
        codings, display = on_sglt2[0]
        drug = vs.sglt2_ingredient(codings, display)
        facts["current_sglt2"] = drug or display
        reason = f"Already on SGLT2 inhibitor: {display}"
        if drug and drug not in vs.SGLT2_DEMONSTRATED_BENEFIT.values():
            # D13: still not applicable, but flag the agent for the clinician
            reason += (f" ({drug} has no kidney outcome trial; 11.7a recommends an agent"
                       " with demonstrated benefit)")
        return Result(NOT_APPLICABLE, [reason], facts)

    # 4. CKD: coded diagnosis OR persistent lab evidence
    reasons = []
    ckd_dx = has_active(p.conditions, vs.CKD, as_of)
    low_egfr = persistent(p.egfr, lambda v: v < CKD_EGFR_MAX, as_of,
                          CKD_LAB_LOOKBACK_DAYS, CKD_PERSIST_DAYS)
    high_uacr = persistent(p.uacr, lambda v: v >= UACR_CKD_MIN, as_of,
                           CKD_LAB_LOOKBACK_DAYS, CKD_PERSIST_DAYS)
    if ckd_dx:
        reasons.append(f"CKD diagnosis: {ckd_dx.display}")
    if low_egfr:
        reasons.append(f"eGFR < {CKD_EGFR_MAX} on 2 results >= {CKD_PERSIST_DAYS} days apart")
    if high_uacr:
        reasons.append(f"UACR >= {UACR_CKD_MIN} mg/g on 2 results >= {CKD_PERSIST_DAYS} days apart")
    facts.update(ckd_dx=bool(ckd_dx), ckd_low_egfr=low_egfr, ckd_high_uacr=high_uacr)
    if not reasons:
        return Result(NOT_APPLICABLE, ["No evidence of CKD"], facts)

    # 5. Recent eGFR at or above the initiation threshold
    day = latest_day(p.egfr, as_of)
    if not day or (as_of - day[0].when).days > EGFR_LOOKBACK_DAYS:
        return Result(INSUFFICIENT_DATA,
                      reasons + [f"No eGFR in the last {EGFR_LOOKBACK_DAYS} days"], facts)
    when = day[0].when
    values = sorted(l.value for l in day)
    lo, hi = values[0], values[-1]
    facts["latest_egfr"] = (lo, when.isoformat())
    if len(values) > 1:
        facts["same_day_egfr"] = values
    # D15: several results on the latest day. If they straddle the threshold
    # we can't tell which is right, so say so; otherwise use the lowest.
    if lo < EGFR_INITIATION_MIN <= hi:
        shown = ", ".join(f"{v:g}" for v in values)
        return Result(INSUFFICIENT_DATA,
                      reasons + [f"Conflicting eGFR results on {when}: {shown} "
                                 f"(on both sides of {EGFR_INITIATION_MIN})"], facts)
    e = Lab(lo, day[0].unit, when)
    facts["suggested_agents"] = SUGGESTED_AGENTS
    if e.value < EGFR_INITIATION_MIN:
        return Result(NOT_APPLICABLE,
                      reasons + [f"Latest eGFR {e.value:g} < {EGFR_INITIATION_MIN} (below initiation threshold)"],
                      facts)

    return Result(RECOMMEND,
                  [f"Type 2 diabetes ({t2d.display})"] + reasons +
                  [f"Latest eGFR {e.value:g} on {e.when} (>= {EGFR_INITIATION_MIN})"
                   + (f"; lowest of {len(values)} results that day" if len(values) > 1 else ""),
                   "Not currently on an SGLT2 inhibitor",
                   "Agents with demonstrated benefit (ADA 11.7a): " + ", ".join(SUGGESTED_AGENTS)],
                  facts)


# --- Layer 2: FHIR JSON -> PatientData (pure) ----------------------------------

def _date(s):
    if not s:
        return None
    return datetime.fromisoformat(s[:10]).date()


def _status(cc):
    for c in (cc or {}).get("coding", []):
        if c.get("code"):
            return c["code"]
    return ""


def _obs_value(o):
    q = o.get("valueQuantity")
    if not q or q.get("value") is None:
        return None
    return float(q["value"]), q.get("unit") or q.get("code") or ""


def _obs_date(o):
    return _date(o.get("effectiveDateTime") or (o.get("effectivePeriod") or {}).get("start")
                 or o.get("issued"))


def build_patient_data(patient, conditions, observations, med_requests, medications=None):
    """Convert raw FHIR resources (dicts) into PatientData.

    medications: optional {"Medication/123": resource} for MedicationRequests
    that reference a Medication instead of coding the drug inline.
    """
    medications = medications or {}
    names = patient.get("name") or [{}]
    name = " ".join(names[0].get("given", []) + [names[0].get("family", "")]).strip()
    p = PatientData(id=patient.get("id", ""), name=name,
                    birth_date=_date(patient.get("birthDate")),
                    deceased=bool(patient.get("deceasedDateTime") or patient.get("deceasedBoolean")),
                    deceased_date=_date(patient.get("deceasedDateTime")))

    for c in conditions:
        code = c.get("code") or {}
        p.conditions.append(Dx(
            codings=code.get("coding", []),
            clinical_status=_status(c.get("clinicalStatus")),
            verification=_status(c.get("verificationStatus")),
            onset=_date(c.get("onsetDateTime")),
            abatement=_date(c.get("abatementDateTime")),
            display=code.get("text") or next((x.get("display", "") for x in code.get("coding", [])), ""),
        ))

    for o in observations:
        if o.get("status") in ("entered-in-error", "cancelled", "preliminary"):
            continue
        codings = (o.get("code") or {}).get("coding", [])
        val, when = _obs_value(o), _obs_date(o)
        if val is None or when is None:
            continue
        lab = Lab(value=val[0], unit=val[1], when=when)
        if vs.in_valueset(codings, vs.EGFR):
            p.egfr.append(lab)
        elif vs.in_valueset(codings, vs.UACR):
            p.uacr.append(lab)

    for mr in med_requests:
        if mr.get("status") != "active":
            continue
        ref = (mr.get("medicationReference") or {}).get("reference", "")
        if "medicationCodeableConcept" in mr:
            cc = mr["medicationCodeableConcept"]
        else:
            cc = (medications.get(ref) or {}).get("code") or {}
        codings = cc.get("coding", [])
        display = cc.get("text") or next((x.get("display", "") for x in codings), "") or ref
        p.active_meds.append((codings, display))
    return p


# --- Layer 1: fetching from a FHIR server --------------------------------------

class Fhir:
    def __init__(self, base):
        self.base = base.rstrip("/")
        self.s = requests.Session()
        self.s.headers["Accept"] = "application/fhir+json"

    def get(self, path, **params):
        r = self.s.get(f"{self.base}/{path}", params=params or None, timeout=120)
        r.raise_for_status()
        return r.json()

    def search(self, rtype, **params):
        """Yield every matching resource, following `next` links across pages."""
        bundle = self.get(rtype, **params)
        while True:
            for e in bundle.get("entry", []):
                if e.get("search", {}).get("mode", "match") == "match":
                    yield e["resource"]
            nxt = next((l["url"] for l in bundle.get("link", []) if l["relation"] == "next"), None)
            if not nxt:
                return
            r = self.s.get(nxt, timeout=120)
            r.raise_for_status()
            bundle = r.json()

    def included(self, rtype, **params):
        """Like search(), but also return _include'd resources keyed by reference."""
        bundle = self.get(rtype, **params)
        matches, extra = [], {}
        while True:
            for e in bundle.get("entry", []):
                res = e["resource"]
                if e.get("search", {}).get("mode", "match") == "match":
                    matches.append(res)
                else:
                    extra[f"{res['resourceType']}/{res['id']}"] = res
            nxt = next((l["url"] for l in bundle.get("link", []) if l["relation"] == "next"), None)
            if not nxt:
                return matches, extra
            r = self.s.get(nxt, timeout=120)
            r.raise_for_status()
            bundle = r.json()


def token_list(valueset):
    return ",".join(f"{sys_}|{code}" for sys_, codes in valueset.items() for code in sorted(codes))


def fetch_patient_data(fhir, pid):
    patient = fhir.get(f"Patient/{pid}")
    conditions = list(fhir.search("Condition", patient=pid, _count=200))
    labs = {vs.LOINC: vs.EGFR[vs.LOINC] | vs.UACR[vs.LOINC]}
    observations = list(fhir.search("Observation", patient=pid,
                                    code=token_list(labs), _count=200))
    meds, med_refs = fhir.included("MedicationRequest", patient=pid, status="active",
                                   _include="MedicationRequest:medication", _count=200)
    return build_patient_data(patient, conditions, observations, meds, med_refs)


def candidate_patient_ids(fhir):
    """Patients with any T2D-coded Condition. evaluate() makes the real decision."""
    ids = set()
    for c in fhir.search("Condition", code=token_list(vs.TYPE2_DIABETES),
                         _elements="subject", _count=500):
        ref = c.get("subject", {}).get("reference", "")
        if ref.startswith("Patient/"):
            ids.add(ref.split("/", 1)[1])
    return sorted(ids)


# --- CLI -----------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", default="http://localhost:8080/fhir")
    ap.add_argument("--patient", help="Evaluate one patient and print details")
    ap.add_argument("--as-of", type=date.fromisoformat, default=date.today(),
                    help="Evaluation date (YYYY-MM-DD). Default: today")
    ap.add_argument("--csv", help="Write cohort results to this CSV file")
    args = ap.parse_args(argv)

    fhir = Fhir(args.base)

    if args.patient:
        p = fetch_patient_data(fhir, args.patient)
        r = evaluate(p, args.as_of)
        print(f"{p.name} ({p.id}), born {p.birth_date}")
        print(f"  {r.status}")
        for reason in r.reasons:
            print(f"   - {reason}")
        print(f"  facts: {r.facts}")
        return 0

    ids = candidate_patient_ids(fhir)
    print(f"Evaluating {len(ids)} patients with a T2D-coded condition (as of {args.as_of})\n")
    rows, counts = [], {}
    for pid in ids:
        p = fetch_patient_data(fhir, pid)
        r = evaluate(p, args.as_of)
        counts[r.status] = counts.get(r.status, 0) + 1
        rows.append({"patient_id": pid, "name": p.name, "status": r.status,
                     "reasons": " | ".join(r.reasons),
                     "latest_egfr": "{} ({})".format(*r.facts["latest_egfr"])
                                    if "latest_egfr" in r.facts else ""})
        print(f"  {r.status:18} {p.name:30} {r.reasons[-1]}")

    print("\n== Summary ==")
    for k in (RECOMMEND, NOT_APPLICABLE, INSUFFICIENT_DATA):
        print(f"  {k:18} {counts.get(k, 0)}")
    if args.csv:
        with open(args.csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["patient_id"])
            w.writeheader()
            w.writerows(rows)
        print(f"\nWrote {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
