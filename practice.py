#!/usr/bin/env python3
"""
practice.py - my own FHIR exercises (Phase 1, Step 6).

Run:  python practice.py --base http://localhost:8080/fhir
      python3 practice.py --patient PATIENT_ID      # run exercise 1 on one patient

Structure:
  1. Fhir        - tiny client. search() follows `next` links so paging is handled.
  2. helpers     - small functions for FHIR's awkward nested shapes.
  3. exercises   - one function per checkbox in the guide. #1 is worked through
                   as an example; the rest are stubs with hints.
"""
import argparse
from itertools import islice
import sys
from collections import defaultdict
import json
from unittest import result

import requests

from collections import Counter, defaultdict
from datetime import datetime, date
import matplotlib.pyplot as plt
import time

# ---------------------------------------------------------------------------
# Code constants. A "clinical concept" is really a (system, code) pair.
# ---------------------------------------------------------------------------
SNOMED = "http://snomed.info/sct"
LOINC = "http://loinc.org"
RXNORM = "http://www.nlm.nih.gov/research/umls/rxnorm"

TYPE2_DIABETES = f"{SNOMED}|44054006"
HYPERTENSION = f"{SNOMED}|59621000"
HBA1C = f"{LOINC}|4548-4"
# eGFR: Synthea may use more than one LOINC code. Find the one(s) your server
# actually has by looking at Observation resources for a diabetic patient.
EGFR = f"{LOINC}|33914-3"  # TODO: confirm against your data


# ---------------------------------------------------------------------------
# 1. Client
# ---------------------------------------------------------------------------
class Fhir:
    def __init__(self, base):
        self.base = base.rstrip("/")
        self.session = requests.Session()
        self.session.headers["Accept"] = "application/fhir+json"
        self.request_count = 0

    def get(self, url, params=None):
        self.request_count += 1
        """GET one URL and return parsed JSON. Accepts a full URL or a path."""
        if not url.startswith("http"):
            url = f"{self.base}/{url.lstrip('/')}"
        r = self.session.get(url, params=params, timeout=60)
        r.raise_for_status()
        return r.json()

    def search(self, resource_type, **params):
        """Yield every resource matching a search, following `next` links.

        A search returns a Bundle (type=searchset). Each entry's `resource`
        is a match. If the server has more, the Bundle's `link` list has an
        entry with relation == "next" - we keep following it until it's gone.

        Note: python kwargs can't contain '-', so for params like
        clinical-status pass them with a dict: search("Condition", **{"clinical-status": "active"})
        """
        params.setdefault("_count", 100)
        bundle = self.get(resource_type, params=params)
        while True:
            for entry in bundle.get("entry", []):
                yield entry["resource"]
            next_url = next(
                (l["url"] for l in bundle.get("link", []) if l["relation"] == "next"),
                None,
            )
            if not next_url:
                return
            bundle = self.get(next_url)  # next URL already contains the params

    def count(self, resource_type, **params):
        """Number of matches, without downloading them (_summary=count)."""
        return self.get(resource_type, params={**params, "_summary": "count"})["total"]


# ---------------------------------------------------------------------------
# 2. Helpers for FHIR's nested shapes
# ---------------------------------------------------------------------------
def display(codeable):
    """Human-readable text from a CodeableConcept ({text, coding: [...]})."""
    if not codeable:
        return "?"
    if codeable.get("text"):
        return codeable["text"]
    codings = codeable.get("coding", [])
    return codings[0].get("display", codings[0].get("code", "?")) if codings else "?"


def ref_id(reference):
    """'Encounter/123' -> '123'.  Takes the Reference dict ({'reference': ...})."""
    if not reference or "reference" not in reference:
        return None
    return reference["reference"].split("/")[-1]


def encounter_start(enc):
    """Encounter dates live in period.start (a visit has a start and an end)."""
    return enc.get("period", {}).get("start", "")


def observation_value(obs):
    """Return (number, unit) from an Observation's valueQuantity, else (None, None)."""
    q = obs.get("valueQuantity")
    return (q["value"], q.get("unit", "")) if q else (None, None)

def peek(resource):
       print(json.dumps(resource, indent=2)[:3000])


# ---------------------------------------------------------------------------
# 2.5. Practice
# ---------------------------------------------------------------------------
def gender_breakdown(fhir):
    counts = Counter()
    for patient in fhir.search("Patient"):
        counts[patient.get("gender", "unknown")] += 1
    return counts

def latest_observation(fhir, patient_id, code):
    obs = next(
        fhir.search("Observation", patient=patient_id, code=code,
                    _sort="-date", _count=1),
        None,
    )
    if obs is None:
        return None
    value, unit = observation_value(obs)
    return value, unit, obs.get("effectiveDateTime", "")[:10]

def patients_with_condition(fhir, code, active_only=True):
    params = {"code": code}
    if active_only:
        params["clinical-status"] = "active"
    return {ref_id(c["subject"]) for c in fhir.search("Condition", **params)}

def lab_range_by_patient(fhir, code):
    values = defaultdict(list)
    for obs in fhir.search("Observation", code=code):
        number, _ = observation_value(obs)
        if number is None:
            continue
        values[ref_id(obs["subject"])].append(number)
    return {pid: (min(v), max(v)) for pid, v in values.items()}

def age_in_years(fhir, patient_id):
    patient = fhir.get(f"Patient/{patient_id}")
    born = date.fromisoformat(patient["birthDate"])
    today = date.today()
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))

def average_age_with_condition(fhir, code):
    ids = patients_with_condition(fhir, code)
    ages = [age_in_years(fhir, pid) for pid in ids]
    return sum(ages) / len(ages) if ages else None

# ---------------------------------------------------------------------------
# 3. Exercises
# ---------------------------------------------------------------------------
def patient_timeline(fhir, patient_id):
    """Exercise 1: every encounter in date order, with the diagnoses made at each.

    Plan:
      a) fetch the patient's Encounters, sorted oldest-first
      b) fetch the patient's Conditions ONCE (not once per encounter)
      c) group conditions by the encounter they point to (Condition.encounter)
      d) print each encounter followed by its conditions

    Step (b)+(c) is the pattern to remember: one big query + group locally
    beats N small queries.
    """
    encounters = list(fhir.search("Encounter", patient=patient_id, _sort="date"))

    conditions_by_encounter = defaultdict(list)
    for cond in fhir.search("Condition", patient=patient_id):
        enc_id = ref_id(cond.get("encounter"))  # None if the condition has no encounter
        conditions_by_encounter[enc_id].append(cond)

    print(f"Timeline for Patient/{patient_id}: {len(encounters)} encounters")
    for enc in encounters:
        kind = display((enc.get("type") or [{}])[0])
        print(f"\n{encounter_start(enc)[:10]}  {kind}")
        for cond in conditions_by_encounter.get(enc["id"], []):
            status = display(cond.get("clinicalStatus"))
            print(f"    - {display(cond.get('code'))}  [{status}]")

    # Worth a look: conditions that point at no encounter at all.
    orphans = conditions_by_encounter.get(None, [])
    if orphans:
        print(f"\n({len(orphans)} conditions had no encounter reference)")


def plot_a1c(fhir, patient_id):
    """Exercise 2: plot one diabetic patient's A1c over time.

    Hints:
      - fhir.search("Observation", patient=patient_id, code=HBA1C, _sort="date")
      - date is in obs["effectiveDateTime"]; value via observation_value(obs)
      - import matplotlib.pyplot as plt; plt.plot(dates, values, marker="o")
      - draw a horizontal line at 7.0 (a common treatment target) with plt.axhline
      - parse dates with datetime.fromisoformat(s[:10]) so the x-axis is real time
    """
    observations = list(fhir.search("Observation", patient=patient_id, code=HBA1C, _sort="date"))

    dates, values = [], []
    for obs in observations:
        number = observation_value(obs)[0]
        if number is None:
            continue
        dates.append(datetime.fromisoformat(obs["effectiveDateTime"][:10]))
        values.append(number)

    if not values: print("No A1c results for this patient"); return

    plt.plot(dates, values, marker="o")
    plt.axhline(y=7.0, color="r", linestyle="--")
    plt.xlabel("Date")
    plt.ylabel("A1c (%)")
    plt.title(f"A1c Over Time for Patient/{patient_id}")
    plt.show()


def hypertension_and_diabetes(fhir):
    """Exercise 3: how many patients have hypertension, and what fraction also have diabetes?

    Hints:
      - Condition search returns conditions, NOT patients. Collect the set of
        patient IDs: ref_id(cond["subject"])
      - Do it for HYPERTENSION and for TYPE2_DIABETES, then use set intersection (&)
      - Decide: all conditions, or only clinical-status=active? Try both and
        notice whether the answer changes.
    """
    diabetic_pids = patients_with_condition(fhir, TYPE2_DIABETES)

    hypertensive_pids = patients_with_condition(fhir, HYPERTENSION)

    both = diabetic_pids & hypertensive_pids

    print(f"\nPatients with hypertension: {len(hypertensive_pids)}")
    print(f"Patients with type 2 diabetes: {len(diabetic_pids)}")
    print(f"Patients with both: {len(both)}")
    fraction = len(both) / len(hypertensive_pids) if hypertensive_pids else 0.0
    print(f"Fraction of hypertensive patients who also have diabetes: {fraction:.1%}")


def low_egfr_patients(fhir, threshold=60):
    """Exercise 4: patients whose MOST RECENT eGFR is below `threshold`.

    Hints:
      - "Most recent" is per patient. One approach: for each patient, ask the
        server for _sort=-date&_count=1 (see latest_value() in explore.py).
      - Another: pull all eGFR observations, sort by date, keep the last one per patient.
      - Why is "any eGFR below 60 ever" the wrong question?
    """
    print(f"\n== Patients whose most recent eGFR is below {threshold} ==")
    observations = list(fhir.search("Observation", code=EGFR, _sort="-date"))

    latest_by_patient = {}
    for obs in observations:
        pid = ref_id(obs["subject"])
        if pid not in latest_by_patient:
            latest_by_patient[pid] = obs

    low_patients = []
    for pid, obs in latest_by_patient.items():
        value, unit = observation_value(obs)
        if value is not None and value < threshold:
            low_patients.append((pid, value, unit, obs.get("effectiveDateTime", "")[:10]))

    print(f"Found {len(low_patients)} patients with low eGFR.\n")
    for pid, value, unit, date in low_patients:
        patient = fhir.get(f"Patient/{pid}")
        name = patient.get("name", [{}])[0]
        full_name = " ".join(name.get("given", []) + [name.get("family", "")])
        print(f"  {full_name}  (id {pid})  eGFR: {value:.1f} {unit} ({date})")

def patients_on_medication(fhir, rxnorm_code):
    """Exercise 5: every patient with an ACTIVE prescription for one drug.

    Hints:
      - MedicationRequest?status=active&code=http://www.nlm.nih.gov/research/umls/rxnorm|CODE
      - Some servers/data put the drug in a separate Medication resource. If
        the code search returns nothing, look at one MedicationRequest to see
        which shape it uses (medicationCodeableConcept vs medicationReference).
    """
    if "|" not in rxnorm_code:
        rxnorm_code = f"{RXNORM}|{rxnorm_code}"

    med_requests = list(fhir.search("MedicationRequest", status="active", code=rxnorm_code))

    patient_ids = {ref_id(mr["subject"]) for mr in med_requests}

    print(f"\nPatients with active prescriptions for {rxnorm_code}: {len(patient_ids)}\n")
    for pid in patient_ids:
        patient = fhir.get(f"Patient/{pid}")
        name = patient.get("name", [{}])[0]
        full_name = " ".join(name.get("given", []) + [name.get("family", "")])
        print(f"  {full_name}  (id {pid})")


def resolved_conditions(fhir, limit=15):
    """Exercise 6: find a Condition with clinicalStatus 'resolved' and read abatementDateTime."""
    print(f"\n== First {limit} resolved conditions ==")
    search = fhir.search("Condition", **{"clinical-status": "resolved"})
    with_end = 0
    for cond in islice(search, limit):
        end = cond.get("abatementDateTime")
        with_end += end is not None
        print(f"{display(cond.get('code')):45} "
              f"onset {cond.get('onsetDateTime', '?')[:10]}  "
              f"abated {(end or 'none')[:10]}  "
              f"verification: {display(cond.get('verificationStatus'))}")
    print(f"\n{with_end} of {limit} have an abatementDateTime")


def diabetes_cohort_fast(fhir):
    """Exercise 7: build the diabetes cohort's A1c values in a few requests, not one per patient.

    Hints:
      - One Observation search with code=HBA1C and NO patient filter, paged
        via fhir.search(), gets everyone's A1cs at once.
      - Group by ref_id(obs["subject"]) and keep the newest per patient.
      - Or try _include / chained search (e.g. subject:Patient...) if your server supports it.
      - Time both versions; the difference is the point.
    """
    print("\n== Diabetes cohort's most recent A1c values ==")
    diabetic_pids = patients_with_condition(fhir, TYPE2_DIABETES)

    latest_a1c_by_patient = {}
    for obs in fhir.search("Observation", code=HBA1C, _sort="-date"):
        pid = ref_id(obs["subject"])
        if pid in diabetic_pids and pid not in latest_a1c_by_patient:
            latest_a1c_by_patient[pid] = obs

    for pid, obs in latest_a1c_by_patient.items():
        value, unit = observation_value(obs)
        if value is None:
            continue
        date = obs.get("effectiveDateTime", "")[:10]
        patient = fhir.get(f"Patient/{pid}")
        name = patient.get("name", [{}])[0]
        full_name = " ".join(name.get("given", []) + [name.get("family", "")])
        print(f"{full_name}  (id {pid})  A1c: {value:.1f} {unit} ({date})")

def diabetes_cohort_slow(fhir):
    """Exercise 7, slow version: one request per patient.

    Hints:
      - For each patient, call latest_value(fhir, pid, HBA1C) to get their most recent A1c.
      - Time both versions; the difference is the point.
    """
    print("\n== Diabetes cohort's most recent A1c values (slow version) ==")
    diabetic_pids = patients_with_condition(fhir, TYPE2_DIABETES)

    for pid in diabetic_pids:
        result = latest_observation(fhir, pid, HBA1C)
        if result and result[0] is not None:
            a1c = f"{result[0]:.1f} {result[1]} ({result[2]})"
        else:
            a1c = "none recorded"
        patient = fhir.get(f"Patient/{pid}")
        name = (patient.get("name") or [{}])[0]
        full_name = " ".join(name.get("given", []) + [name.get("family", "")])
        print(f"{full_name}  (id {pid})  Latest A1c: {a1c or 'none recorded'}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def pick_a_patient(fhir):
    """Grab the first diabetic patient on the server, handy for testing."""
    for cond in fhir.search("Condition", code=TYPE2_DIABETES, _count=1):
        return ref_id(cond["subject"])
    sys.exit("No type 2 diabetes patients found. Is the server loaded?")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8080/fhir")
    ap.add_argument("--patient", help="Patient ID (default: first diabetic patient found)")
    args = ap.parse_args()

    fhir = Fhir(args.base)
    try:
        fhir.get("metadata", params={"_summary": "true"})  # is the server up?
    except requests.RequestException as e:
        sys.exit(f"Can't reach {args.base}: {e}\nTry: docker ps")

    pid = args.patient or pick_a_patient(fhir)
    #patient_timeline(fhir, pid)

    # As you finish each exercise, call it here:
    # plot_a1c(fhir, pid)

    print(gender_breakdown(fhir))

    hypertension_and_diabetes(fhir)

    plot_a1c(fhir, 9785)

    low_egfr_patients(fhir, threshold=60)

    patients_on_medication(fhir, "996740")  # Memantine hydrochloride 2 MG/ML Oral Solution

    resolved_conditions(fhir, limit=15)

    before = fhir.request_count
    start = time.perf_counter()
    diabetes_cohort_fast(fhir)
    print(f"Fast version: {fhir.request_count - before} requests, {time.perf_counter() - start:.1f} seconds")

    before = fhir.request_count
    start = time.perf_counter()
    diabetes_cohort_slow(fhir)
    print(f"Slow version: {fhir.request_count - before} requests, {time.perf_counter() - start:.1f} s")

if __name__ == "__main__":
    main()