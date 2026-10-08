"""
Expand the SGLT2 inhibitor ingredients into every RxNorm product code that
contains them, using the free NLM RxNav API, and save to sglt2_rxnorm.json.

Why: MedicationRequests are coded at the product level ("dapagliflozin 10 MG
Oral Tablet", "dapagliflozin / metformin ER tablet [Xigduo]"), so matching on
the five ingredient codes alone would miss almost every real prescription.

Run once, commit the JSON (it's a code list, not patient data), and rerun
every few months as new products appear.

    python3 build_sglt2_valueset.py
"""

import json
import sys
from datetime import date
from pathlib import Path

import requests

from valuesets import SGLT2_INGREDIENTS

RXNAV = "https://rxnav.nlm.nih.gov/REST"
# Clinical drug, branded drug, generic pack, branded pack
PRODUCT_TTYS = "SCD+SBD+GPCK+BPCK"


def products_for(ingredient_rxcui):
    r = requests.get(f"{RXNAV}/rxcui/{ingredient_rxcui}/related.json",
                     params={"tty": PRODUCT_TTYS}, timeout=30)
    r.raise_for_status()
    out = {}
    for group in r.json().get("relatedGroup", {}).get("conceptGroup", []):
        for c in group.get("conceptProperties", []) or []:
            out[c["rxcui"]] = c["name"]
    return out


def main():
    all_codes = {}
    for rxcui, name in SGLT2_INGREDIENTS.items():
        found = products_for(rxcui)
        print(f"{name:15} {rxcui:>8}  {len(found)} products")
        all_codes.update(found)
    out = {
        "description": "RxNorm products containing an SGLT2 inhibitor",
        "built": date.today().isoformat(),
        "source": RXNAV,
        "codes": sorted(all_codes),
        "names": all_codes,
    }
    path = Path(__file__).with_name("sglt2_rxnorm.json")
    path.write_text(json.dumps(out, indent=2))
    print(f"Wrote {len(all_codes)} codes to {path}")


if __name__ == "__main__":
    sys.exit(main())
