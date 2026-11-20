# Skuld

> Skuld is the Expectation dimension's analysis in the Asgard suite: it relates what an application version is
> observed to do (O) and what its provider declares (D) to each other and to a normative frame, and reports concerns,
> never verdicts, to the Investigator.

**State: 0.7.1.** Built: the assessment of an application version (`skuld assess`), with the rule tier, the
expectation stage (`skuld expect`), the reasoning tier (`skuld judge`), qualification as its last stage (cases, their
qualified results and next steps; [`plan/archive/QUALIFICATION_PLAN.md`](../plan/archive/QUALIFICATION_PLAN.md)), the aggregate of its concerns
(`skuld aggregate`), experiments chosen by the assessment
(`skuld select`, `propose`, `run`, `analyse`), the provenance check (`skuld check`) and the calibration against an
expert (`skuld calibrate`). Not built: the reasoning tier's argument form (P10). The model is E's technical report
([`ODE/expectation/expectation.tex`](../ODE/expectation/expectation.tex), version 0.9); the plan and its history,
[`plan/archive/SKULD_REDESIGN_PLAN.md`](../plan/archive/SKULD_REDESIGN_PLAN.md). How Skuld works is in
[`docs/architecture.md`](docs/architecture.md). Checked against the code on 2026-11-20.

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
`OLLAMA_API_KEY` where the server asks for one). `SKULD_CONFIG` names another `config.json`; `SKULD_PROFILE` or
`skuld --profile <name>` lays a named profile over it (see Configuration).

## Quick start

The assessment of an application version, from O's and D's reports (the experiments are optional and off by default):

```bash
skuld describe workspaces/app@1.0 --package com.example.app --version 1.0 \
    --observation <O report>=<run> --declaration <D report> --exploration <Loki exploration>   # assessment.yaml
skuld expect workspaces/app@1.0      # stage-1 samples: expectation/<batch>/s<seed>/
skuld judge workspaces/app@1.0       # stage-2 samples: assessment/<question>/<subject>/s<seed>/
skuld assess workspaces/app@1.0      # subjects.json, assessment.json, assessment.md; no model asked
skuld aggregate workspaces/app@1.0   # aggregate.json, aggregate.md: the concerns as aggregated concerns a reader can work through
skuld check workspaces/app@1.0       # every digest and pointer resolves, the assessment rebuilds identically
                                     # (with the reading and notice definition it names)
```

## Commands

| Command | Does | Reads | Writes | Model |
|---|---|---|---|---|
| `skuld config` | the configuration in force: its file, profile, digest and content; `--profiles` lists the profiles | `config.json`, `profiles/` | – | no |
| `skuld compat add <ws>` | states that D of one version speaks for O's (`--o`, `--d`, `--reason`, `--author`) | `assessment.yaml` | `assessment.yaml` | no |
| `skuld describe <ws>` | describes an assessment workspace | O's and D's reports, the exploration, the frame, the corpus | `assessment.yaml` | no |
| `skuld expect <ws>` | the expectation stage's samples, without D | O's practices, the exploration's screens, the corpus | `expectation/`, `manifests/expect_<time>.json` | yes |
| `skuld judge <ws>` | the reasoning tier's samples: specificity first (a declared purpose judged not specific specifies nothing), then compatibility and minimisation; `--question compatibility` alone reads the kept specificity samples, so ask specificity first | stage-1 samples, D's declarations, the norms | `assessment/`, `manifests/judge_<time>.json` | yes |
| `skuld assess <ws>` | the assessment, ending with its qualification | everything above, kept samples, the case report | `subjects.json`, `assessment.json`, `assessment.md` | no |
| `skuld aggregate <ws>` | groups the assessment's concerns into aggregated concerns and themes by structural keys, and its open conditions by text; lossless | `assessment.json` | `aggregate.json`, `aggregate.md` | no |
| `skuld review draw\|score\|agree <folder> …` | the reviewers' non-blind verification of aggregated concerns, blind to the model run: draws units from several runs' aggregates, scores agreement (per unit and per member), anchoring and misses, and two reviewers' κ | `aggregate.json`, `assessment.json`, the reviews | `sample.json`, `key.json`, `scores.json`, `agreement.json` | no |
| `skuld review export <package.zip> <samples…> --reviewer <id>` / `import <returned.zip> <reviews folder>` | a reviewer's standalone package (the review tool with its modules, their samples without key or manifest, launchers, a guide, a packer for the returns), and the filing of what they send back | drawn samples; a returned zip | a zip; `<sample>-<id>/reviews.json` | no |
| `skuld review exclude <sample> <new folder> <workspaces…>` | a drawn sample without the units of applications withdrawn after the draw (`--application`, `--reason`) | a drawn sample | a new sample folder | no |
| `skuld review expect-draw\|expect-score\|expect-agree <folder> …` | the reviewers' check of a sample of the expectation stage's predictions, blind to the model run: per practice its purposes (plausible, DPV node, beneficiary, role, citations) and stated dependencies (relationship, steps), judged against the stage's own context; agreement per question, purposes missed, two reviewers' κ | `assessment.json`, `expectation/`, the reviews | `sample.json`, `key.json`, `scores.json`, `agreement.json` | no |
| `skuld check <ws>` | the provenance check and the rebuild, with the reading (`skuld.judge.reading`) and the notice definition (`ratatoskr.notices`; 1.1.0 if the report names none) the report names; a report made under earlier method versions is noted, not refused | the workspace | – (exit status) | no |
| `skuld select <ws>` | chooses experiments, within the budget, in the order `inputs/chosen.yaml` gives; or lists the candidates or their groups | `assessment.json`, `inputs/chosen.yaml` | `inputs/selection.json`; with `--list` or `--groups` JSON lines on stdout | no |
| `skuld propose <exploration>` | generates experimental cases from Loki's exploration and the catalogue | the exploration, `catalogue/` | a case workspace's inputs, `proposals/`, `manifests/propose_<time>.json` | yes |
| `skuld freeze <ws>` | fixes inputs written by hand, by digest | `cases/` (the experimental cases), `oracles/` | `frozen.json` | no |
| `skuld change <ws> <input>` | records a change of a fixed input | the input | `frozen.json` | no |
| `skuld run <ws>` | the replays of each condition, through Loki, in rotated order; first the installed version (adb), which must be the recording's and the workspace's or stated compatible with them | the experimental cases, Loki's base configuration | `configs/`, `runs.jsonl`, Loki's run folders | no |
| `skuld analyse <ws>` | the case report of the experiments | the runs, Verðandi's reports, the oracles | `observation/`, `report.json`, `report.md` | no |
| `skuld calibrate draw <dir> <ws>…` | draws a calibration sample for an expert's blind review; several workspaces of one application (one per model family) are merged across families | assessments | `<dir>/`: `sample.json`, `key.json`, `documents/`, `manifest.json` | no |
| `skuld calibrate score <dir>` | error rates from the expert's decisions | `<dir>/reviews.json` | `<dir>/scores.json` | no |
| `skuld calibrate check <dir> <ws>…` | whether a calibration holds for other assessments | their components | – (exit status) | no |
| `skuld calibrate agree <dir> <a> <b>` | two reviewers' agreement (Cohen's kappa) and their disagreements | two reviews files | `<dir>/agreement.json`; `<dir>/reviews.json` seeded with the agreed decisions if absent | no |
| `skuld corpus check` | passages without source or date, about nothing, with an id other than their file's, or without a person's check (`verified: {by, date}`) | `corpus/` | – | no |
| `skuld corpus coverage <reports>` | recipients and data of O's reports no passage covers | O's reports | – | no |
| `skuld corpus keep` | before `corpus/` changes: copies it, with its norms, to `corpora/<first 8 of its digest>/`, checked to have the same digest | `corpus/` | `corpora/<digest>/` | no |
| `skuld corpus repoint <ws…>` | after the change: every workspace whose `corpus.path` is `corpus/` but whose digest is a kept one gets its path rewritten to the kept copy, and nothing else; a workspace whose corpus was not kept is listed and fails the command | `assessment.yaml`, `corpora/` | `assessment.yaml`, `corpora/<digest>-repointed.tsv` | no |
| `skuld purposes map <ws…> --out <map>` | places the purpose nodes stage 1 invented (outside the vocabulary) at the nearest node by the similarity of embeddings; extends an existing map, keeping its labels | stage-1 answers | the map (see `purpose_map`) | an embedding model |
| `skuld catalogue` | the catalogue's families, each with its review (who, when) or "not reviewed"; `--review <id>@<version> --by <person>` records one | `catalogue/` | `catalogue/reviews/<id>@<version>.yaml` | no |

Options (from `--help`):

| Command | Options |
|---|---|
| `describe` | `--package`, `--version`, `--observation <report>[=<run>] …`, `--declaration`, `--exploration`, `--corpus`, `--comment`, `--frame`, `--frame-version`, `--model` (written as `models:`) |
| `expect` | `--model` (default: the assessment's, else config.json's), `--api` (default: config's `client.api`), `--seeds …`, `--offline` (only the samples kept), `--corpus` (default: the one `assessment.yaml` names), `--registry` |
| `judge` | `--model` (default: the assessment's, else config.json's), `--api` (default: config's `client.api`), `--seeds …`, `--question specificity\|compatibility\|minimisation …`, `--offline`, `--corpus` (default: the one `assessment.yaml` names), `--registry` |
| `assess`, `check` | `--registry` |
| `select` | `--replace` (replace a fixed selection, keeping it) or `--extend` (add to a fixed selection, keeping its choices; what an earlier budget refused is decided again), `--budget-seconds` (over config.json's), `--list` (the candidates as JSON lines: device time, eligible, could change; writes nothing), `--groups` (the candidates' groups, data type × purpose, as JSON lines) |
| `propose` | `--pilot <pilot>` or `--workspace <folder>`, `--catalogue`, `--model`, `--api` (default: config's `client.api`), `--offline`, `--selection <selection.json>`, `--registry` |
| `freeze` | `--author` (required), `--model` (the author is a model), `--prompt` |
| `change` | `--reason` (required) |
| `run` | `--recorded <Loki run>`, `--config <Loki configuration>`, `--device <adb serial>` (all required), `--conditions …` (default `all`: baseline and every alternative of the workspace's experimental cases), `--repeat` (3), `--loki` (the sibling Loki), `--qualify` (one baseline replay first), `--case` (replay only up to the end of this experimental case's path), `--keep-going` (Loki goes on after an action it could not replay), `--json` (one JSON line per run) |
| `analyse` | `--offline` (existing observation reports only) |
| `calibrate` | `--per-stratum`, `--seed` (default: config.json's; draw only), `--registry` |
| `review` | `--per-stratum`, `--per-run`, `--anchor`, `--seed`, `--step` (draw); `--prefix`, `--per-app` (expect-draw); `--reviewer` (export); `--application`, `--reason` (exclude) |
| `corpus` | `--corpus` (default: Skuld's); `--dry-run` (repoint: list only) |
| `purposes` | `--out` (required), `--model` (default `qwen3-embedding:8b-fp16`, on the server of `OLLAMA_BASE_URL`) |
| `catalogue` | `--catalogue` (default: Skuld's); `--review <family>`, `--by <person>`, `--note` |

`--registry` names the recipient registry (default: `config.json`'s `registry.path`, else Ratatoskr's built one); give
`propose`, `expect`, `judge`, `assess` and `check` the same one, or none. Where `registry.sha256` pins a build, a
registry of other content is refused.

## Configuration

`config.json`, laid over Ratatoskr's defaults (`ratatoskr/config.json`):

| Key | Default | Meaning |
|---|---|---|
| `model` | `gemma4:31b` | the model of the generator and both stages |
| `sampling.default` | temperature 1.0, `top_p` 0.95, `top_k` 64; `max_tokens` 8192 | gemma4's recommended sampling, for every task that `sampling.tasks` or a profile does not set otherwise (Ratatoskr's seed 42) |
| `sampling.tasks.propose` | seed 1 | the generator |
| `client.api`, `.timeout` | `ollama`, 5400 s | the provider (the default of `--api`) and its timeout (the gateway allows about 100 minutes; qwen3.8 at `xhigh` took up to 30 minutes, queue included) |
| `client.cache.enabled` | false | no response cache: the kept samples are Skuld's record of every answer |
| `client.limits` | 128 requests at a time for gemma4:31b, 256 for qwen3.8:27b, 4 for others | per model, within what the gateway recommends ([`../docs/INFERENCE_GUIDE.md`](../docs/INFERENCE_GUIDE.md): 128–160 and 256–384); the study's profiles keep theirs (timeout 1800 s, fewer requests at a time) |
| `client.retry_budget` | 1800 s | a failed request is retried, with jittered backoff, as long as the time since its first attempt stays within this (Ratatoskr 0.32.0), so that a gateway outage of minutes is waited out |
| `client.max_tokens_cap` | 32768 | an answer cut off at its token limit is asked again with twice the limit, up to this; one still cut off is refused (kept aside as `answer.length.json` with `record.length.json`, counted `truncated`): the question's next attempt is asked, told so, and the cut-off attempt is asked again next run |
| `expectation.seeds`, `assessment.seeds` | 1, 2, 3 | the samples per batch or question |
| `expectation.think`, `assessment.think` | `xhigh` | the model's thinking (null: the model's default; a level: its effort). On the gateway a level is qwen3.8's effort (`low`, `medium`; `high` and `xhigh` both its top effort) but, since 20 Nov 2026 03:26, a cap on gemma4's thinking tokens (`low` 1,024, `medium` 4,096, `high` 16,384, `xhigh` none); `low` cuts most of gemma4's thinking short |
| `expectation.traffic` | off | stage 1 sees excerpts of the practice's traffic |
| `expectation.topup` | off | stage 1 asks again, alone, for the practices its batches left out |
| `expectation.batch_size` | none | at most this many practices per batch: an episode's practices are split, in order, into batches `e<episode>.<n>` with the same screens (one remedy, to be measured, for qwen3.8 answering only a batch's first practice) |
| `assessment.known_data_only` | off | the practices whose datum O could not identify are left out |
| `registry.path`, `.sha256` | none, the rerun's build, `ba786d32…` (2026-11-20: Ratatoskr 0.33.0, the ownership list 0.33.0, the sources fetched that day) | the recipient registry and the digest of the build a study decides on (Ratatoskr's `Registry.from_config`): a registry of other content, or none, is refused; unset, Ratatoskr's built one, unchecked |
| `vocabularies.<id>` | the bundled version | the version of a vocabulary, e.g. `{"dpv-purposes": "2.3"}`: the purpose vocabulary's nodes are part of the stage-1 prompt, so samples asked under one version are found only under it |
| `prompts.<id>` | the current version | an earlier version of a prompt (`skuld/templates.py`; kept as `skuld/prompts/versions/<id>-<version>.md`), so that samples asked with it are found again |
| `purpose_map` | none | invented purpose nodes mapped to the vocabulary's: a path (relative to the repository), or `{path, sha256}`, refused if the file's digest differs |
| `experiments.budget_seconds` | 0 | device time for experiments; 0 is off |
| `experiments.repeats`, `.run_seconds` | 3, 240 | runs per condition and a run's expected length, for the budget (`skuld run --repeat` sets the runs made) |
| `calibration.per_stratum`, `.seed` | 10, 1 | units drawn per stratum; the draw's seed |
| `judge.attempts.<question>` | 2 | how often a question is asked, the refusal given back; the last answer, refused or not, is read as far as it holds (no sample only where every attempt was cut off) |
| `review.per_run`, `.floor`, `.anchor`, `.seed` | 70, 3, 0, 1 | the review of aggregated concerns: units per run, the least per stratum, units shown blind first, the draw's seed |
| `expectation_review.per_stratum`, `.seed` | 8, 1 | the review of stage-1 predictions |
| `components.loki`, `.verdandi` | none | the command used instead of the sibling's `.venv` |

A **profile** (`profiles/<name>.json`) holds only what differs from `config.json` and is laid over it key by key (a
list or a value replaces the one below), chosen by `skuld --profile <name>` or `SKULD_PROFILE`. The profiles are the
setups a study ran with, so that they can be run again elsewhere; every run manifest records the profile and the
digest of the configuration in force (`configuration`), and `skuld config` shows it.

| Profile | The setup of |
|---|---|
| `study-2026-11-gemma-vendor` | the Expectation paper's final gemma4:31b run (13 Nov 2026): vendor sampling (temperature 1.0, `top_p` 0.95, `top_k` 64), reasoning low (on the gateway then: thinking without a limit; asked anew today, `low` caps gemma4's thinking at 1,024 tokens), `max_tokens` 32,768, traffic, top-up, known data only, the study's purpose map; timeout 1800 s, 8 requests at a time |
| `study-2026-11-qwen-low-traffic-topup` | its final qwen3.8:27b run: temperature 0.4, reasoning low, `max_tokens` 32,768, traffic, top-up, known data only, the study's purpose map; timeout 1800 s, 128 requests at a time |
| `gemma-xhigh` | gemma4:31b as in the study's final run for stages 1 and 2 (vendor sampling, `max_tokens` 32,768, traffic, top-up, known data only, the study's purpose map), with thinking `xhigh`; the generator's sampling and the client's timeout and limits from `config.json` |
| `qwen-xhigh` | qwen3.8:27b with its recommended sampling for thinking (temperature 1.0, `top_p` 0.95, `top_k` 20, `min_p` 0) and thinking `xhigh`, otherwise as `gemma-xhigh` |
| `fixtures-2026-10` | the three fixtures in `workspaces/`: `config.json` until 20 Nov 2026 (temperature 0.4 for both stages, 0.2 for the generator, `max_tokens` 8192, the model's default thinking); their kept samples are found only under it |

Every profile above but the two `xhigh` ones also names what its samples were asked with that has changed since:
`dpv-purposes` 2.3 (2.3.1, Ratatoskr 0.32.0, adds a node, which changes the stage-1 prompt) and the prompts before
20 Nov 2026 (expectation and expectation_traffic 4, specificity and compatibility 1, minimisation 2), when the context
moved to the end of every prompt and the minimisation prompt came to say "list no entry for it".

The study's profiles state every value they had from `config.json` at the time, so that a later `config.json` changes
no study run. They keep the options their samples record, `think` among them: a sample's options identify it, so a
profile that asked `xhigh` where its run recorded `low` would keep none of the run's samples. Since the gateway made
gemma4's levels caps (20 Nov 2026), a question the gemma4 profile asks anew thinks less than the run's did.

The study's purpose map is `purpose-maps/study-2026-11.json` (digest `2c8e24b1ddb8…`, as its assessments name it),
built on `dpv-purposes` 2.3 by the study's script, whose method is now `skuld purposes map`; a map is extended only on
the vocabulary version it was built on.

## Files

An assessment workspace holds one application version; in a pilot it is `pilots/<pilot>/skuld/<package>@<version>/`,
the case study's are in `workspaces/` (local data, ignored by Git; `cases/` until 20 Nov 2026, renamed since "case"
is the unit of qualification, and an experiment's case is an experimental case):

```text
<workspace>/
  assessment.yaml                  O's reports, D's report, the exploration, the frame, the corpus, each by digest;
                                   the models (models:); optionally compatible_versions (written by hand, see below)
  subjects.json                    practices, declarations, the collection, comparability, parties, the frame's conditions
  expectation/<batch>/s<seed>/     a stage-1 sample: record, context, prompt, answer (a2/: asked again with the refusal;
                                   answer.length.json, record.length.json: an answer cut off at its limit; topup/<practice>/: asked alone)
  assessment/<question>/<subject>/s<seed>/   a stage-2 sample: specificity, compatibility, minimisation (a<n>/ as above)
  manifests/<command>_<time>.json  the run manifest of expect, judge and propose
  assessment.json, assessment.md   the assessment (expectation_assessment)
  aggregate.json, aggregate.md     its concerns as aggregated concerns (expectation_aggregate; skuld/aggregate.py says how)
  inputs/selection.json            the choice of experiments, each choice and refusal with its reason
  inputs/chosen.yaml               concerns or practices chosen first: pursued by the author, or in the calibration sample
  workspace.yaml                   for experiments: the application, where its runs are, how Verðandi is called
                                   (verdandi) and with which annotators (verdandi_options, e.g. --model, --student)
  cases/<case>.yaml                an experimental case: feature, purposes with requirements and oracle, components, search space
  oracles/<id>@<v>.yaml            success and invalid conditions, measurements with direction and tolerance
  frozen.json                      every input's digest, when it was fixed, its author and its changes
  proposals/                       the generator's prompts and answers per episode
  configs/, runs.jsonl             Loki's configuration per condition; the runs, in order
  qualification.json               the experimental cases the qualifying replay did not qualify, with why (not the assessment's
                                   qualification, which is in assessment.json)
  observation/<run>/               Verðandi's report of each run
  report.json, report.md           the case report (expectation_report)
  superseded/<date>/               samples a re-ask replaced
```

O's and D's claims are related only where O's installed version equals D's store version. Where they differ and the
author judges them comparable, `assessment.yaml` states it, and the statement is a named input of the assessment
(`version_compatibility`), checked by `skuld check`:

```yaml
compatible_versions:
- versions: ['3.8.96', '3.8.100']
  reason: why D of the one version speaks for the other
  author: {kind: person, id: <who>}
  fixed: '2026-10-31T21:15:00+00:00'
```

Beside the workspaces: `corpus/` (passages of documentation and, in `corpus/norms/`, the norms; each passage tagged with
what it is `about` and verified against its source by a person, `verified: {by, date}`), `corpora/<digest>/` (earlier
corpora that workspaces still name), `profiles/`, `purpose-maps/`, `catalogue/families/<id>@<version>.yaml` (the
generator's feature families; local until deployed), and a calibration sample's folder
(`pilots/<pilot>/calibration/<id>/`; the fixtures' in `calibration/`, ignored by Git). The blind review tool is
[`tools/calibration-review/`](tools/calibration-review/README.md); it also serves the review of aggregated concerns
(`skuld review`).

## Tests

```bash
uv run pytest                     # 436 tests on 2026-11-20
ruff format . && ruff check .
```

Tests that read local data skip without it: the three fixtures' assessments are rebuilt and checked when `workspaces/` holds
them (Pilates Workout 1.6.4, NeuroNation 3.8.96, WetterOnline 2026.20), under the profile they were asked with
(`fixtures-2026-10`; by hand: `skuld --profile fixtures-2026-10 check workspaces/<fixture>`); one test reads a real Loki run
(`SKULD_RUN_DIR`, or the latest captured and instrumented run in the sibling `Loki/runs/`); one analyses the dry run's
case workspace (`SKULD_DRY_RUN`, or the Pilates fixture). Earlier copies of the Pilates workspace are in
`workspaces/archive/`.

## Documentation

| Document | Content |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | How Skuld works: the figures, its interfaces, how an assessment is made, the modules, the data model, the design rules, the limits |
| [`docs/scientific-summary.md`](docs/scientific-summary.md) | The method for a scientific audience, in the notation of E's report |
| [`tools/calibration-review/README.md`](tools/calibration-review/README.md) | The expert's blind review of a calibration sample |
| [`ODE/expectation/expectation.tex`](../ODE/expectation/expectation.tex) | The model: E's technical report |
| [`plan/archive/SKULD_REDESIGN_PLAN.md`](../plan/archive/SKULD_REDESIGN_PLAN.md) | The plan, its reviews and measurements, what is done and open |
| [`Loki/docs/architecture.md`](../Loki/docs/architecture.md#capture) (Capture, Instrumentation) | The capture and instrumentation of a run, which Skuld reads |
| [`docs/DOCUMENTATION_STANDARD.md`](../docs/DOCUMENTATION_STANDARD.md) | The standard these documents follow |

## License

GPL-3.0-only, see [LICENSE](LICENSE).
