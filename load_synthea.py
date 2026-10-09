"""
Load Synthea FHIR bundles into a FHIR server (e.g. a local HAPI FHIR server).

Synthea's patient bundles refer to hospitals and clinicians with *conditional
references* like "Organization?identifier=...". Those only resolve if the
hospital and practitioner files are loaded first, so this script loads:

    1. hospitalInformation*.json
    2. practitionerInformation*.json
    3. every patient bundle

It is safe to re-run:
  - Hospitals and practitioners use conditional creates, so HAPI skips ones
    it already has.
  - Patients already on the server are skipped (looked up by their Synthea
    identifier). A failed patient bundle is rolled back as a whole, so
    re-running retries exactly the ones that failed.

By default it drops billing and document resources (Claim,
ExplanationOfBenefit, DocumentReference, Provenance). They're over half of
each file, nothing clinical points to them, and this project doesn't use
them. Pass --keep-all to load everything.

Usage:
    python load_synthea.py --dir ./output/fhir --base http://localhost:8080/fhir
    python load_synthea.py --workers 2          # load two patients at a time
    python load_synthea.py --keep-all           # include billing/documents
"""

import argparse
import glob
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

HEADERS = {"Content-Type": "application/fhir+json", "Accept": "application/fhir+json"}
SYNTHEA_ID_SYSTEM = "https://github.com/synthetichealth/synthea"
SKIP_TYPES = {"Claim", "ExplanationOfBenefit", "DocumentReference", "Provenance"}
FAILURE_LOG = "load_failures.log"
MAX_FAILS_IN_A_ROW = 3


def ordered_files(directory):
    all_files = sorted(glob.glob(os.path.join(directory, "*.json")))
    hospitals = [f for f in all_files if os.path.basename(f).startswith("hospitalInformation")]
    practitioners = [f for f in all_files if os.path.basename(f).startswith("practitionerInformation")]
    patients = [f for f in all_files if f not in hospitals and f not in practitioners]
    return hospitals, practitioners, patients


def slim(bundle):
    """Remove resource types we don't use. Returns how many entries were dropped."""
    before = len(bundle.get("entry", []))
    bundle["entry"] = [e for e in bundle.get("entry", [])
                       if e.get("resource", {}).get("resourceType") not in SKIP_TYPES]
    return before - len(bundle["entry"])


def synthea_patient_id(bundle):
    for e in bundle.get("entry", []):
        r = e.get("resource", {})
        if r.get("resourceType") == "Patient":
            for ident in r.get("identifier", []):
                if ident.get("system") == SYNTHEA_ID_SYSTEM:
                    return ident.get("value")
    return None


def already_loaded(session, base, synthea_id):
    r = session.get(f"{base}/Patient",
                    params={"identifier": f"{SYNTHEA_ID_SYSTEM}|{synthea_id}", "_summary": "count"},
                    headers=HEADERS, timeout=60)
    r.raise_for_status()
    return r.json().get("total", 0) > 0


def error_summary(resp):
    """Pull the human-readable message out of the server's OperationOutcome."""
    try:
        issues = resp.json().get("issue", [])
        msgs = [i.get("diagnostics") or i.get("details", {}).get("text", "") for i in issues]
        msg = " | ".join(m for m in msgs if m)
        if msg:
            return msg[:400]
    except ValueError:
        pass
    return resp.text[:400]


def load_file(base, path, keep_all, check_existing):
    """Load one bundle. Returns (status, detail) where status is ok/skipped/failed."""
    session = requests.Session()
    with open(path, encoding="utf-8") as fh:
        bundle = json.load(fh)

    if check_existing:
        sid = synthea_patient_id(bundle)
        if sid and already_loaded(session, base, sid):
            return "skipped", "already on server"

    dropped = 0 if keep_all else slim(bundle)
    body = json.dumps(bundle).encode("utf-8")
    t0 = time.time()
    resp = session.post(base, data=body, headers=HEADERS, timeout=1800)
    secs = time.time() - t0
    if resp.ok:
        return "ok", f"{len(body) / 1e6:.1f} MB, {secs:.0f}s" + (f", dropped {dropped}" if dropped else "")
    return "failed", f"HTTP {resp.status_code} after {secs:.0f}s: {error_summary(resp)}"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", default="./output/fhir", help="Folder with Synthea FHIR JSON files")
    parser.add_argument("--base", default="http://localhost:8080/fhir", help="FHIR server base URL")
    parser.add_argument("--workers", type=int, default=1,
                        help="Patient bundles to load at once (default 1; try 2-3)")
    parser.add_argument("--keep-all", action="store_true",
                        help="Also load Claim, ExplanationOfBenefit, DocumentReference, Provenance")
    args = parser.parse_args()
    base = args.base.rstrip("/")

    try:
        requests.get(f"{base}/metadata", headers=HEADERS, timeout=30).raise_for_status()
    except requests.RequestException as exc:
        sys.exit(f"Can't reach the FHIR server at {base}: {exc}")

    hospitals, practitioners, patients = ordered_files(args.dir)
    if not patients:
        sys.exit(f"No patient .json files found in {args.dir}")

    counts = {"ok": 0, "skipped": 0, "failed": 0}
    failures = []
    start = time.time()

    def report(i, total, name, status, detail):
        counts[status] += 1
        label = {"ok": "ok     ", "skipped": "skipped", "failed": "FAILED "}[status]
        print(f"[{i}/{total}] {label} {name}  ({detail})", flush=True)
        if status == "failed":
            failures.append((name, detail))
            with open(FAILURE_LOG, "a", encoding="utf-8") as log:
                log.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {name}\n    {detail}\n")

    # 1-2. Shared resources, in order, one at a time. Stop if these fail:
    # every patient would fail after them.
    for path in hospitals + practitioners:
        name = os.path.basename(path)
        status, detail = load_file(base, path, keep_all=True, check_existing=False)
        print(f"{status:8} {name}  ({detail})", flush=True)
        if status == "failed":
            with open(FAILURE_LOG, "a", encoding="utf-8") as log:
                log.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {name}\n    {detail}\n")
            sys.exit("Hospital/practitioner file failed to load, so patient bundles would fail too. "
                     f"See {FAILURE_LOG}.")

    # 3. Patients, smallest first so you see progress early.
    patients.sort(key=os.path.getsize)
    total = len(patients)
    print(f"\nLoading {total} patient bundles with {args.workers} worker(s)"
          f"{'' if args.keep_all else ', skipping billing/document resources'}\n")
    streak = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(load_file, base, p, args.keep_all, True): p for p in patients}
        for i, fut in enumerate(as_completed(futures), 1):
            name = os.path.basename(futures[fut])
            try:
                status, detail = fut.result()
            except (requests.RequestException, ValueError) as exc:
                status, detail = "failed", f"{type(exc).__name__}: {exc}"
            report(i, total, name, status, detail)
            streak = streak + 1 if status == "failed" else 0
            if streak >= MAX_FAILS_IN_A_ROW:
                for f in futures:
                    f.cancel()
                print(f"\n{MAX_FAILS_IN_A_ROW} failures in a row: the server has probably crashed "
                      "or run out of memory. Stopping. Check `docker logs hapi --tail 200`, "
                      "restart HAPI, then re-run this script to pick up where it left off.")
                break

    minutes = (time.time() - start) / 60
    print(f"\nDone in {minutes:.1f} min: {counts['ok']} loaded, {counts['skipped']} already there, "
          f"{counts['failed']} failed.")
    if failures:
        print(f"Failure details are in {FAILURE_LOG}. Re-run this script to retry just those.")


if __name__ == "__main__":
    main()
