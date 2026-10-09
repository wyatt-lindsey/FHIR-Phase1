# Informing Patient Care with Study Data

A learning project working toward a clinical decision support tool: software that reads a patient's record from an EHR, compares it with current research and guidelines, and suggests treatments a physician may want to consider.

> **Not for clinical use.** This project uses synthetic data only. Its output is not medical advice, and any recommendation logic must be validated by hand against its source guideline.

## Roadmap

| Phase | Goal | Status |
| --- | --- | --- |
| 1. Local FHIR server | Run a HAPI FHIR server loaded with Synthea patients, and query it with curl and Python | In progress |
| 2. Generate patients | Create a few hundred synthetic patients and explore full records | Part of Phase 1 setup |
| 3. Encode one guideline | Turn one recommendation (e.g. SGLT2 inhibitors for type 2 diabetes with chronic kidney disease) into code with defined code sets | Not started |
| 4. CDS Hooks service | Wrap the logic as a web service and test it in the CDS Hooks sandbox | Not started |
| Later | Learn CQL for portable rules; connect to REDCap study data | Not started |

## Repository layout

```
.
├── README.md
├── .gitignore
├── load_synthea.py        # Loads Synthea bundles into a FHIR server, in the right order
├── explore.py             # First queries: counts, condition codes, a diabetes cohort
└── docs/
    └── phase1-local-fhir-server-guide.md
```

## Quick start

Full step-by-step instructions are in [docs/phase1-local-fhir-server-guide.md](docs/phase1-local-fhir-server-guide.md).

**Requirements:** Docker Desktop (4 GB+ memory), Java JDK 17 or newer, Python 3.10+.

1. Start a local FHIR server:

   ```bash
   docker run -d --name hapi -p 8080:8080 hapiproject/hapi:latest
   ```

2. Install the Python dependency:

   ```bash
   python -m pip install requests
   ```

3. Download `synthea-with-dependencies.jar` from the [Synthea setup page](https://github.com/synthetichealth/synthea/wiki/Basic-Setup-and-Running) into the repo folder, then generate patients:

   ```bash
   java -jar synthea-with-dependencies.jar -s 42 -p 15 -a 40-80 Massachusetts
   ```

4. Load them into the server:

   ```bash
   python load_synthea.py --dir ./output/fhir --base http://localhost:8080/fhir
   ```

5. Explore the data:

   ```bash
   python explore.py --base http://localhost:8080/fhir
   ```

## Reproducing the data

Generated data is not committed. Running Synthea with the same seed recreates the same patients:

```bash
java -jar synthea-with-dependencies.jar -s 42 -p 15 -a 40-80 Massachusetts
```

If you change the seed, population size, or age range, update the command here so others can reproduce your data.

## Start/Stop FHIR Server

To stop the server, run:
```bash
   docker compose stop hapi
   ```
To start the server, run:
```bash
   docker compose start hapi
   ```

## Data rules

- **Synthetic data only** for now. Real patient data is governed by HIPAA and requires working inside a healthcare institution.
- **Real patient data never goes in this repository**, public or private.
- The Synthea jar and the generated `output/` folder are excluded by `.gitignore`. They're large (the jar is about 200 MB, and single patient files can be tens of MB) and can always be regenerated.

## Key standards

| Term | What it is |
| --- | --- |
| FHIR | REST API standard for clinical data, with resources like `Patient` and `Observation` as JSON |
| Synthea | Open-source generator of realistic synthetic patients as FHIR |
| HAPI FHIR | Open-source FHIR server, run locally in Docker |
| LOINC, SNOMED CT, ICD-10, RxNorm | Code systems for labs, clinical concepts, diagnoses, and drugs |
| CDS Hooks | Spec where an EHR sends patient context to a service and gets back suggestion "cards" |
| REDCap | Web platform for collecting and storing research study data |

## Project lead

Wyatt Lindsey
