# Exploratory network-IaC paper

[main.tex](main.tex) is an English, venue-neutral working draft, not a claim of
submission readiness. Author information and a broader literature review remain
to be completed. The draft distinguishes:

- **Measured:** final compilation/schema results, visible-policy convergence,
  paired differences, workflow latency, and observed token consumption.
- **Unassessed:** human requirement satisfaction, deployment/runtime correctness,
  general model superiority, and the causal source of the AWS gap.

The original completed run is the primary population, including its operational
failure. The authorized replacement of NET-10/M2 is reported separately as a
sensitivity analysis. Original and recovered outcomes are never pooled as
independent repetitions.

## Regenerate the evidence snapshot

From the repository root, using the configured venv:

```powershell
.\.venv\Scripts\python.exe docs\paper\export_results.py --run results\human-requirements\study-20261026T145746Z-ec1e8589
```

This does not authenticate, call a model, rerun validators, or deploy resources.
It reads the original completed checkpoint preserved in the operational-retry
audit, the current checkpoint, and final saved validator reports.
The exporter fails on missing generated-candidate evidence instead of fabricating
zeroes or successful outcomes. A failed generation can legitimately lack a
validator report and is represented as unknown compilation evidence.

- [generated/results.json](generated/results.json) contains aggregate counts,
  model/target strata, paired transitions, token coverage, the common-intent
  sensitivity, retry provenance, and source/validator hashes. It contains no
  generated infrastructure source code or credentials.
- [generated/results.tex](generated/results.tex) contains generated numerical
  macros and table rows. Do not edit numerical results by hand.

The aggregate snapshot is committed with the paper only when an author explicitly
chooses to commit it; the original local raw run remains ignored by Git. Public
raw-data availability is not claimed. Refreshing against another run requires
scientific review of the narrative as well as successful extraction.

## Build locally

With an existing TeX installation:

```powershell
Set-Location docs\paper
latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex
```

This workspace was also validated with the official Tectonic 0.17.0 Windows binary,
stored locally in the ignored `.tools` directory:

```powershell
Set-Location docs\paper
..\..\.tools\tectonic\tectonic.exe -k --keep-logs main.tex
```

Tectonic compiles and resolves the BibTeX bibliography locally. Its first build
may download TeX support files; no manuscript upload or external typesetting
service is required. Build products are ignored; the LaTeX source, bibliography,
and exported aggregate snapshot are the persistent paper sources.
On this Windows host, Tectonic emits a missing-default-Fontconfig diagnostic.
The build succeeds; the resulting PDF was checked for embedded fonts, resolved
citations/cross-references, rendered numerical results, and text overflow.

## Defensibility and next steps

The defensible scope is a **descriptive exploratory study of convergence to the
configured static validators**. Both models have zero AWS one-shot visible passes,
and the compiling initial candidates share flow-logging/default-security-group
violations. Feedback gains are not independent evidence of semantic correctness:
the feedback source and measured endpoint use the same validators, and some policy
requirements are not explicit in the initial scenario.

Before a stronger empirical submission, freeze a prospective analysis, validate
an independent requirements rubric with blinded expert grading, address
ambiguity/policy-disclosure ablations, justify repetitions, and review the artifact
release. The paper already records the unbalanced target matrix, one repetition,
model/service uncertainty, operational interruptions, Terraform-language
restrictions, and the absence of deployment/runtime evidence.
