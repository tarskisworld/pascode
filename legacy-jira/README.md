# Shared existing YAML-dialect Jira tooling

Six implementations serve both CDT and BRB: build_analysis, build_mapped,
extended_checks, generate_test_suite_from_yaml, run_generated_static_tests and
validate_ontology_mapping. Eleven instance scripts now delegate to these packaged
implementations. They make no network requests or deployment mutations.

The instance's `jira-as-code/analysis/legacy-context.json` supplies site/account
labels, optional existing dialect sections, legacy manifest formatting and any
historical evidence sample. These values do not belong in software. Schemas,
declarations, ontology reference data and generated evidence remain with their
owning instance. The algorithms and implementation-step mapping are shared.

Environment integration command:

```bash
bash /home/alan/src/cloisterdorateura/ControlPlane/tooling/jira-analysis \
  build_mapped PASCODE_ROOT OUTPUT_ROOT
```

Choose any of the six existing command names. Inputs mount read-only; generated
analysis/mapped files go to the explicitly selected output root. Prompt commands
retain script arguments; their explicit paths refer to `/inputs` and `/outputs`
inside the worker. Calling an existing instance Python wrapper requires the pinned
engine image, which includes `/legacy-jira`; old bare Python images lack the package.
No Docker socket is required inside that worker.

The original BRB analyzer embedded DEV/KAN/SAM1 and called that sample live. The
sample is now explicit instance evidence, and future generated reports label it
historical. CDT reports remain not-observed. Existing generated reports are untouched.
Differential migration verification compared all eleven commands on disposable
copies of both declarations, excluding volatile timestamps and this evidence-label
correction. The archived originals and result are in the private migration records.

These tools retain the legacy YAML dialect. They do not make it execution-compatible
with MainSystem's JSON-schema contracts. No schema redesign, new deployment adapter,
shared daemon or `.pascode` folder migration is included.
