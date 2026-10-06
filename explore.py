"""
First queries against a local FHIR server loaded with Synthea data.

Usage:
    python explore.py                      # run everything
    python explore.py --base http://localhost:8080/fhir
"""

import argparse
from collections import Counter

import requests

HEADERS = {"Accept": "application/fhir+json"}

# Code systems are identified by URLs. A token search is written "system|code".
SNOMED = "http://snomed.info/sct"
LOINC = "http://loinc.org"

TYPE2_DIABETES = f"{SNOMED}|44054006"   # Diabetes mellitus type 2 (disorder)
HBA1C = f"{LOINC}|4548-4"               # Hemoglobin A1c/Hemoglobin.total in Blood
EGFR = f"{LOINC}|33914-3"               # eGFR (MDRD), what Synthea records


class Fhir:
    def __init__(self, base):
        self.base = base.rstrip("/")

    def get(self, url, params=None):
        resp = requests.get(url, params=params, headers=HEADERS, timeout=120)
        resp.raise_for_status()
        return resp.json()

    def search(self, resource_type, params=None, max_pages=None):
        """Yield every matching resource, following the Bundle's 'next' links."""
        bundle = self.get(f"{self.base}/{resource_type}", params)
        pages = 1
        while True:
            for entry in bundle.get("entry", []):
                yield entry["resource"]
            next_url = next((l["url"] for l in bundle.get("link", []) if l["relation"] == "next"), None)
            if not next_url or (max_pages and pages >= max_pages):
                return
            bundle = self.get(next_url)
            pages += 1

    def count(self, resource_type, params=None):
        params = dict(params or {}, _summary="count")
        return self.get(f"{self.base}/{resource_type}", params).get("total")


def first_coding(codeable_concept):
    coding = (codeable_concept or {}).get("coding", [{}])[0]
    return coding.get("code"), coding.get("display")


def show_counts(fhir):
    print("\n== How much data is there? ==")
    for rtype in ["Patient", "Encounter", "Condition", "Observation", "MedicationRequest"]:
        print(f"  {rtype:<18} {fhir.count(rtype)}")


def top_conditions(fhir, n=20):
    print(f"\n== Top {n} condition codes ==")
    tally = Counter()
    # _elements trims each resource down to the fields we need, which is much faster.
    for cond in fhir.search("Condition", {"_count": 500, "_elements": "code"}):
        tally[first_coding(cond.get("code"))] += 1
    for (code, display), count in tally.most_common(n):
        print(f"  {count:>5}  {code:<16} {display}")


def latest_value(fhir, patient_id, code):
    obs = next(fhir.search("Observation", {
        "patient": patient_id, "code": code, "_sort": "-date", "_count": 1,
    }, max_pages=1), None)
    if not obs:
        return None
    q = obs.get("valueQuantity", {})
    date = (obs.get("effectiveDateTime") or "")[:10]
    if q.get("value") is None:
        return f"no numeric value ({date})"
    return f"{q['value']:.1f} {q.get('unit', '')} ({date})"


def active_meds(fhir, patient_id):
    names = []
    for mr in fhir.search("MedicationRequest", {"patient": patient_id, "status": "active"}):
        if "medicationCodeableConcept" in mr:
            names.append(first_coding(mr["medicationCodeableConcept"])[1])
        else:
            names.append("(medication given by reference)")
    return names


def diabetes_cohort(fhir, limit=10):
    print("\n== Patients with active type 2 diabetes ==")
    patient_ids = []
    for cond in fhir.search("Condition", {"code": TYPE2_DIABETES, "clinical-status": "active", "_count": 200}):
        pid = cond["subject"]["reference"].split("/")[-1]
        if pid not in patient_ids:
            patient_ids.append(pid)
    print(f"  Found {len(patient_ids)} patients. Showing up to {limit}.\n")

    for pid in patient_ids[:limit]:
        patient = fhir.get(f"{fhir.base}/Patient/{pid}")
        name = patient.get("name", [{}])[0]
        full_name = " ".join(name.get("given", []) + [name.get("family", "")])
        print(f"  {full_name}  (born {patient.get('birthDate')}, id {pid})")
        print(f"    Latest A1c:  {latest_value(fhir, pid, HBA1C) or 'none recorded'}")
        print(f"    Latest eGFR: {latest_value(fhir, pid, EGFR) or 'none recorded'}")
        meds = active_meds(fhir, pid)
        print(f"    Active meds: {', '.join(meds) if meds else 'none'}\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://localhost:8080/fhir")
    args = parser.parse_args()
    fhir = Fhir(args.base)

    show_counts(fhir)
    top_conditions(fhir)
    diabetes_cohort(fhir)


if __name__ == "__main__":
    main()
