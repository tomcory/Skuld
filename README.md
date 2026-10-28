# Skuld

> Skuld is the Expectation dimension's analysis in the Asgard suite: it relates what an application version is
> observed to do (O) and what its provider declares (D) to each other and to a normative frame, and reports concerns,
> never verdicts, to the Investigator.

**State: 0.5.0.** Built: the assessment of an application version (`skuld assess`), with the rule tier, the
expectation stage (`skuld expect`), the reasoning tier (`skuld judge`), experiments chosen by the assessment
(`skuld select`, `propose`, `run`, `analyse`), the provenance check (`skuld check`) and the calibration against an
expert (`skuld calibrate`). Not built: the reasoning tier's argument form (P10). The model is E's technical report
([`ODE/expectation/expectation.tex`](../ODE/expectation/expectation.tex), version 0.6); the plan and its history,
[`SKULD_REDESIGN_PLAN.md`](../SKULD_REDESIGN_PLAN.md). How Skuld works is in
[`docs/architecture.md`](docs/architecture.md). Checked against the code on 2026-10-28.

## Role in Asgard

| | Record | Schema (Ratatoskr) | From / for |
|---|---|---|---|
| reads | O's reports of the version: the exploration, baseline runs | `observation_report` | Verðandi |
| reads | D's report of the version: derived documents, findings, open conditions | `declaration_report` (schema 4) | Urda |
| reads | the exploration's records (screens), Loki's run folders of replays | `run.json`, `events.jsonl`, `captured_http_message`, … | Loki, Heimdall |
| reads | the normative frame, the corpus of norms and documentation | `normative_frame` (`gdpr-art5`); `corpus/` | Ratatoskr; Skuld |
| writes | the assessment, E's report to the Investigator | `expectation_assessment` | Odin, the Investigator |
| writes | the case report of the experiments: runs, verifications, comparisons | `expectation_report` | the assessment |
| asks | replays of an exploration under interventions | Loki's configuration | Loki |

Only Heimdall and Loki touch the device: Skuld asks Loki for runs through Loki's command line and reads the folders
Loki writes. The expectation stage reads nothing of D. An assessment is fixed by digest and rebuilds identically from
the samples it keeps, so `skuld assess` asks no model.

## Setup

Python 3.12 or newer.

```bash
uv sync --all-extras            # or: pip install -e ".[reason,dev]"
```

Ratatoskr comes from the tag `pyproject.toml` pins, over SSH. To work on both, install a checkout of it in editable mode
afterwards (`uv pip install -e ../Ratatoskr`). The extra `reason` brings the model providers, which `skuld propose`,
`expect` and `judge` need. The model's server comes from the environment or Skuld's `.env`: `OLLAMA_BASE_URL` (and
`OLLAMA_API_KEY` where the server asks for one). `SKULD_CONFIG` names another `config.json`.

## Quick start

The assessment of an application version, from O's and D's reports (the experiments are optional and off by default):

```bash
skuld describe cases/app@1.0 --package com.example.app --version 1.0 \
    --observation <O report>=<run> --declaration <D report> --exploration <Loki exploration>   # assessment.yaml
skuld expect cases/app@1.0       # stage-1 samples: expectation/<batch>/s<seed>/
skuld judge cases/app@1.0        # stage-2 samples: assessment/<question>/<subject>/s<seed>/
skuld assess cases/app@1.0       # subjects.json, assessment.json, assessment.md; no model asked
skuld check cases/app@1.0        # every digest and pointer resolves, the assessment rebuilds identically
```

## Commands

| Command | Does | Reads | Writes | Model |
|---|---|---|---|---|
| `skuld describe <ws>` | describes an assessment workspace | O's and D's reports, the exploration, the frame, the corpus | `assessment.yaml` | no |
| `skuld expect <ws>` | the expectation stage's samples, without D | O's practices, the exploration's screens, the corpus | `expectation/` | yes |
| `skuld judge <ws>` | the reasoning tier's samples: specificity, compatibility, minimisation | stage-1 samples, D's declarations, the norms | `assessment/` | yes |
| `skuld assess <ws>` | the assessment | everything above, kept samples, the case report | `subjects.json`, `assessment.json`, `assessment.md` | no |
| `skuld check <ws>` | the provenance check and the rebuild | the workspace | – (exit status) | no |
| `skuld select <ws>` | chooses experiments, within the budget | `assessment.json`, `inputs/chosen.yaml` | `inputs/selection.json` | no |
| `skuld propose <exploration>` | generates cases from Loki's exploration and the catalogue | the exploration, `catalogue/` | a case workspace's inputs, `proposals/` | yes |
| `skuld freeze <ws>` | fixes inputs written by hand, by digest | `cases/`, `oracles/` | `frozen.json` | no |
| `skuld change <ws> <input>` | records a change of a fixed input | the input | `frozen.json` | no |
| `skuld run <ws>` | the replays of each condition, through Loki, in rotated order | the cases, Loki's base configuration | `configs/`, `runs.jsonl`, Loki's run folders | no |
| `skuld analyse <ws>` | the case report of the experiments | the runs, Verðandi's reports, the oracles | `observation/`, `report.json`, `report.md` | no |
| `skuld calibrate draw <dir> <ws>…` | draws a calibration sample for an expert's blind review | assessments | `<dir>/`: `sample.json`, `key.json`, `documents/`, `manifest.json` | no |
| `skuld calibrate score <dir>` | error rates from the expert's decisions | `<dir>/reviews.json` | `<dir>/scores.json` | no |
| `skuld calibrate check <dir> <ws>…` | whether a calibration holds for other assessments | their components | – (exit status) | no |
| `skuld corpus check` | passages without source, date or a person's check | `corpus/` | – | no |
| `skuld corpus coverage <reports>` | recipients and data of O's reports no passage covers | O's reports | – | no |
| `skuld catalogue` | the catalogue's families, reviewed or not | `catalogue/` | – | no |

Options (from `--help`):

| Command | Options |
|---|---|
| `describe` | `--package`, `--version`, `--observation <report>[=<run>] …`, `--declaration`, `--exploration`, `--corpus`, `--comment` |
| `expect` | `--model` (default: config.json's), `--api`, `--seeds …`, `--offline` (only the samples kept), `--corpus`, `--registry` |
| `judge` | `--model` (default: the assessment's, else config.json's), `--api`, `--seeds …`, `--question specificity\|compatibility\|minimisation …`, `--offline`, `--corpus`, `--registry` |
| `assess`, `check` | `--registry` |
| `select` | `--replace` (replace a fixed selection, keeping it) |
| `propose` | `--pilot <pilot>` or `--workspace <folder>`, `--catalogue`, `--model`, `--api`, `--offline`, `--selection <selection.json>`, `--registry` |
| `freeze` | `--author` (required), `--model` (the author is a model), `--prompt` |
| `change` | `--reason` (required) |
| `run` | `--recorded <Loki run>`, `--config <Loki configuration>`, `--device <adb serial>` (all required), `--conditions …`, `--repeat` (3), `--loki` (the sibling Loki), `--qualify` (one baseline replay first) |
| `analyse` | `--offline` (existing observation reports only) |
| `calibrate` | `--per-stratum`, `--seed` (default: config.json's), `--registry` |
| `corpus` | `--corpus` (default: Skuld's) |
| `catalogue` | `--catalogue` (default: Skuld's) |

`--registry` names the recipient registry (default: Ratatoskr's built one); give `propose`, `expect`, `judge`, `assess`
and `check` the same one, or none.

## Configuration

`config.json`, laid over Ratatoskr's defaults (`ratatoskr/config.json`):

| Key | Default | Meaning |
|---|---|---|
| `model` | `gemma4:31b` | the model of the generator and both stages |
| `sampling.default.max_tokens` | 8192 | the answer's limit (Ratatoskr's defaults: temperature 0, seed 42) |
| `sampling.tasks.propose` | temperature 0.2, seed 1 | the generator |
| `sampling.tasks.expect`, `.judge` | temperature 0.4 | the stages; the seed is the sample's |
| `client.api`, `.timeout` | `ollama`, 1800 s | the provider and its timeout |
| `client.cache.enabled` | false | no response cache: the kept samples are Skuld's record of every answer |
| `client.limits` | 4 requests at a time (Ratatoskr's) | per model |
| `expectation.seeds`, `assessment.seeds` | 1, 2, 3 | the samples per batch or question |
| `expectation.think`, `assessment.think` | null | the model's thinking (null: the model's default) |
| `experiments.budget_seconds` | 0 | device time for experiments; 0 is off |
| `experiments.repeats`, `.run_seconds` | 3, 240 | runs per condition; a run's expected length, for the budget |
| `calibration.per_stratum`, `.seed` | 10, 1 | units drawn per stratum; the draw's seed |

## Files

An assessment workspace holds one application version; in a pilot it is `pilots/<pilot>/skuld/<package>@<version>/`,
the case study's are in `cases/` (local data, ignored by Git):

```text
<workspace>/
  assessment.yaml                  O's reports, D's report, the exploration, the frame, the corpus, each by digest
  subjects.json                    practices, declarations, the collection, comparability, parties, the frame's conditions
  expectation/<batch>/s<seed>/     a stage-1 sample: record, context, prompt, answer (a2/: asked again with the refusal)
  assessment/<question>/<subject>/s<seed>/   a stage-2 sample: specificity, compatibility, minimisation
  assessment.json, assessment.md   the assessment (expectation_assessment)
  inputs/selection.json            the choice of experiments, each choice and refusal with its reason
  inputs/chosen.yaml               concerns or practices chosen first: pursued by the author, or in the calibration sample
  workspace.yaml                   for experiments: the application, where its runs are, how Verðandi is called
  cases/<case>.yaml                a case: feature, purposes with requirements and oracle, components, search space
  oracles/<id>@<v>.yaml            success and invalid conditions, measurements with direction and tolerance
  frozen.json                      every input's digest, when it was fixed, its author and its changes
  proposals/                       the generator's prompts and answers per episode
  configs/, runs.jsonl             Loki's configuration per condition; the runs, in order
  qualification.json               the cases the qualifying replay did not qualify, with why
  observation/<run>/               Verðandi's report of each run
  report.json, report.md           the case report (expectation_report)
  superseded/<date>/               samples a re-ask replaced
```

Beside the workspaces: `corpus/` (passages of documentation, `corpus/norms/` the norms, each verified by a person),
`catalogue/families/<id>@<version>.yaml` (the generator's feature families; local until deployed), and a calibration
sample's folder (`pilots/<pilot>/calibration/<id>/`; the fixtures' in `calibration/`, ignored by Git). The blind
review tool is [`tools/calibration-review/`](tools/calibration-review/README.md).

## Tests

```bash
uv run pytest                     # 161 tests on 2026-10-28
ruff format . && ruff check .
```

Tests that read local data skip without it: the three fixtures' assessments are rebuilt and checked when
`cases/` holds them (Pilates Workout 1.6.4, NeuroNation 3.8.96, WetterOnline 2026.20); one test reads a real Loki run
(`SKULD_RUN_DIR`, or the latest captured and instrumented run in the sibling `Loki/runs/`); one analyses the dry run's
case workspace (`SKULD_DRY_RUN`, or the Pilates fixture). Earlier copies of the Pilates workspace are in
`cases/archive/`.

## Documentation

| Document | Content |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | How Skuld works: the figures, its interfaces, how an assessment is made, the modules, the data model, the design rules, the limits |
| [`tools/calibration-review/README.md`](tools/calibration-review/README.md) | The expert's blind review of a calibration sample |
| [`ODE/expectation/expectation.tex`](../ODE/expectation/expectation.tex) | The model: E's technical report |
| [`SKULD_REDESIGN_PLAN.md`](../SKULD_REDESIGN_PLAN.md) | The plan, its reviews and measurements, what is done and open |
| [`Loki/docs/capture.md`](../Loki/docs/capture.md), [`Loki/docs/instrumentation.md`](../Loki/docs/instrumentation.md) | The capture and instrumentation of a run, which Skuld reads |
| [`DOCUMENTATION_STANDARD.md`](../DOCUMENTATION_STANDARD.md) | The standard these documents follow |

## License

GPL-3.0-only, see [LICENSE](LICENSE).
