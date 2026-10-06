"""
Load Synthea FHIR bundles into a FHIR server (e.g. a local HAPI FHIR server).

Synthea's patient bundles refer to hospitals and clinicians with *conditional
references* like "Organization?identifier=...". Those only resolve if the
hospital and practitioner files are loaded first, so this script loads:

    1. hospitalInformation*.json
    2. practitionerInformation*.json
    3. every patient bundle

Usage:
    pip install requests
    python load_synthea.py --dir ./output/fhir --base http://localhost:8080/fhir
"""

import argparse
import glob
import os
import sys
import time

import requests

HEADERS = {"Content-Type": "application/fhir+json", "Accept": "application/fhir+json"}


def ordered_files(directory):
    all_files = sorted(glob.glob(os.path.join(directory, "*.json")))
    hospitals = [f for f in all_files if os.path.basename(f).startswith("hospitalInformation")]
    practitioners = [f for f in all_files if os.path.basename(f).startswith("practitionerInformation")]
    patients = [f for f in all_files if f not in hospitals and f not in practitioners]
    return hospitals + practitioners + patients


def post_bundle(base, path):
    with open(path, "rb") as fh:
        body = fh.read()
    # A bundle is POSTed to the server's base URL, not to a resource endpoint.
    resp = requests.post(base, data=body, headers=HEADERS, timeout=600)
    return resp


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", default="./output/fhir", help="Folder with Synthea FHIR JSON files")
    parser.add_argument("--base", default="http://localhost:8080/fhir", help="FHIR server base URL")
    args = parser.parse_args()

    # Make sure the server is up before sending anything.
    try:
        meta = requests.get(f"{args.base}/metadata", headers=HEADERS, timeout=30)
        meta.raise_for_status()
    except requests.RequestException as exc:
        sys.exit(f"Can't reach the FHIR server at {args.base}: {exc}")

    files = ordered_files(args.dir)
    if not files:
        sys.exit(f"No .json files found in {args.dir}")

    print(f"Loading {len(files)} bundles into {args.base}")
    failures = []
    start = time.time()

    for i, path in enumerate(files, 1):
        name = os.path.basename(path)
        try:
            resp = post_bundle(args.base, path)
        except requests.RequestException as exc:
            failures.append((name, str(exc)))
            print(f"[{i}/{len(files)}] ERROR  {name}: {exc}")
            continue

        if resp.ok:
            print(f"[{i}/{len(files)}] ok     {name}")
        else:
            # The server explains what went wrong in an OperationOutcome resource.
            failures.append((name, resp.text[:500]))
            print(f"[{i}/{len(files)}] FAILED {name} (HTTP {resp.status_code})")

    minutes = (time.time() - start) / 60
    print(f"\nDone in {minutes:.1f} min. {len(files) - len(failures)} succeeded, {len(failures)} failed.")
    for name, detail in failures:
        print(f"\n--- {name} ---\n{detail}")


if __name__ == "__main__":
    main()
