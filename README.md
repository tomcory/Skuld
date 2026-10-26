# Skuld

> Skuld is the Expectation pipeline of the Asgard suite (Expectation dimension of the O/D/E
> framework): purpose-conditioned counterfactual analysis of an app's data practices, resulting in
> E claims.

**State (0.5.0): the assessment of an application version (E report 0.4).** Skuld relates Verðandi's and Urda's
reports of a version to each other and to a normative frame (Ratatoskr's `gdpr-art5`), in two stages, and reports
concerns to the Investigator (`skuld assess`, Ratatoskr's `expectation_assessment`): the subjects (O's practices, D's
declarations and collection); the rule tier (O–D correspondence, transparency, purpose coverage); the expectation
stage (`skuld expect`, without D); the assessment stage's reasoning tier (`skuld judge`: specificity, compatibility,
minimisation, against the norms of `corpus/norms/`); and experiments, chosen by the assessment (`skuld select`), whose
comparisons decide by their strength. One rule combines the claims of every channel and sample, and the report holds
the combined claims, the concerns, what E assessed (its coverage), and the gaps someone could act on. Every claim and
concern carries the uncertainty of what it rests on (technical, semantic, normative; U_n by how the requirement is
tested: low by rule, moderate for a judgement of an open term such as what a purpose needs); the gaps and open
conditions name what the Investigator could acquire or test next; `skuld check` verifies every digest and pointer of
the report and that it rebuilds identically from the same inputs and kept samples. `skuld assess` asks no model.

The experimental channel of E report 0.3 is kept as the assessment's experiments: a workspace of cases and the runs
Loki made for them (`skuld run`, with a qualifying replay first), each intervention verified with Verðandi's report of
the run, the cases' functional oracles and the comparisons (`skuld analyse`: the case report, Ratatoskr's
`expectation_report`, which holds the measurements, from which the assessment makes its claims), and a generator
(`skuld propose`) that writes cases from Loki's exploration and a catalogue of feature families. The plan is [`SKULD_REDESIGN_PLAN.md`](../SKULD_REDESIGN_PLAN.md); the model is
[`ODE/expectation/expectation.tex`](../ODE/expectation/expectation.tex).

## Role in Asgard

Skuld compares what an app does in a baseline run with what it does in a counterfactual run in
which a data flow is withheld or changed. Only Heimdall and Loki touch the device:

- **Loki** drives the app in both runs and applies the intervention from its configuration: it
  controls **Heimdall**'s capture (app scope, blocked hosts) and instruments the app with Frida
  (a data source passed through or changed). Skuld reads the run folders Loki writes, and asks
  Loki for runs through Loki's command line (`loki -c … replay …`, with a configuration that differs
  in the settings of the condition).
- **Verðandi**'s analysis of a run (`verdandi analyse`, called as a command) is a component of
  Skuld's experimental channel: what the app read of a hooked source and where it sent data come
  from its observation report. The records pass between the components in the formats of
  **Ratatoskr**.

Skuld owns the vocabulary of interventions, Loki the mechanisms: Skuld's transformation "location
granularity, from precise to two decimals" becomes `instrumentation.sources.location: "round:2"`
in Loki's configuration. Verification is layered: Loki records whether the app was handed what
the settings say; Skuld decides whether the intervention held, which also needs the traffic and,
for a claim, the functional oracle. A run that Loki did not verify is invalid for Skuld.

## Setup

Python 3.12 or newer.

```bash
pip install -e ".[dev]"
```

Ratatoskr comes from its tag `0.12.0` over SSH. To work on both, install a checkout of it in editable
mode afterwards: `pip install -e "../Ratatoskr[validate]"`.

## Usage

A workspace holds the cases of one application version. A pilot's workspaces are
`pilots/<pilot>/skuld/<package>@<version>/` in Asgard's folder; earlier ones are under `cases/` (local data, ignored by
git):

```text
<workspace>/
  assessment.yaml         the assessment of the version: O's reports, D's report (or none), the exploration (or none),
                          the frame and the corpus, each by digest (`skuld describe` writes it)
  subjects.json           what `skuld assess` built: practices, declarations, the collection, comparability, the
                          recipients' parties, the frame's conditions and every requirement's applicability
  expectation/<batch>/s<seed>/  a stage-1 sample: record (with the notice screens left out), context, prompt, answer
  assessment/<question>/<subject>/s<seed>/  a stage-2 sample (specificity, compatibility, minimisation)
  assessment.json, .md    E's report to the Investigator (Ratatoskr's expectation_assessment): both stages
  inputs/selection.json   the choice of experiments (`skuld select`), each choice and refusal with its reason
  inputs/chosen.yaml      concerns or practices chosen first for experiments, each pursued by the author or in the
                          calibration sample (optional)
  workspace.yaml          application; where the runs are; how Verðandi is called
  cases/<case>.yaml       feature, purposes with requirements and oracle, components, search space
  oracles/<id>@<v>.yaml   success and invalid conditions, measurements with direction and tolerance
  frozen.json             every input's digest, the time it was fixed, its author and its changes
  proposals/              the generator's prompts and answers per episode, and summary.json
  qualification.json      the cases the qualifying replay did not qualify, with why
  runs.jsonl              {"run", "dir", "condition" ('baseline' or an alternative), "order"}
  observation/<run>/      Verðandi's observation report of each run (made where missing)
  report.json, report.md  the case report: the experiments' runs, verifications, decisions and comparisons
  superseded/<date>/      samples a re-ask replaced, kept for the record
```

How Skuld runs is in `config.json`, laid over Ratatoskr's defaults: the default model, the sampling of each task (the
generator at temperature 0.2 from seed 1, both stages at 0.6 with a seed per sample, 8,192
tokens; the stages' seeds), and the
client (Ollama, a 30-minute timeout, no response cache, since the samples are Skuld's record of every answer). The
server's address is read from `OLLAMA_BASE_URL`. The generator and both stages ask through `ask.py`.

An assessment workspace (`assessment.yaml`, written by `skuld describe`) names everything an assessment of the version
reads by digest, the exploration by the records its screens are read from (run.json, events.jsonl, graph.json);
loading it (`inputs.load_assessment`) refuses a report, record, frame or corpus that has changed. A folder that is also a
case workspace holds the experimental channel's cases. The case study's three are Pilates Workout 1.6.4 (baseline
runs, D's report), NeuroNation 3.8.96 (the exploration's O report, D without a policy) and WetterOnline 2026.20
(baseline replays and the exploration, no D).

`skuld assess` builds the subjects. A practice is O's claims aggregated by claim type, data node, recipient (register
entity, else domain) and actor, across the version's O reports, with the episodes and contexts it occurred in and its
configuration u0; a combined claim and the channel claims it combines count once. Declarations are D's claims, by
pointer into D's report. Whether a recipient is the provider or another organisation is decided from the register's
owner, the controller and the e-mail domains D's documents name, and the package's domain; what that leaves open goes
to the Investigator. Each condition of the frame is decided from O's and D's claims by direction: O decides what is
processed, D the legal bases, and a provider's denial is recorded but never makes a requirement inapplicable.

The rule tier asks no model, so it runs on every application. It relates each practice to D's declarations: its data
to the declarations of collection, and a transmission to another organisation to the declared recipients (by entity,
owner, or a category of the recipient's register types; the root category alone corresponds only partially). A denial
contradicts a practice only under what O cannot observe, which becomes an open condition: Google Play's definition of
sharing (a service provider does not count), a legal role the denial names, or the denial's own condition. Declarations
no practice matches are declared without observation, citing O's silence; a practice that aligns with several
declarations relates to all of them, the best alignment deciding. The collection's transparency status per
requirement reads D's annotations on accessible documents and the frame's applicability; a requirement that applies
and is not addressed is concern (i), one that applies only under an undecided condition holds under it. Every claim of
O and D is passed on by reference, related or with the reason it is not.

E also relates the practices and declared purposes to its own expectation, by rule. O–E, per practice, supported
purpose, question and component, names the claims it reads (`to`), and its outcome is a function of them: functional
or recipient dependency (by the value of the deciding Dependency claim, the combination's rule deciding between
them), an alternative demonstrated or technically supported (the deciding claim's level and strength), conflicting,
insufficient evidence or not assessable; an experiment's claims for a case purpose no inferred purpose aligns with
are related per case purpose. D–E, per declared purpose, against the inferred purposes of the practices of its data: supported where every
such practice has a supported purpose the declared node covers, partially where some do, not established where none
does; too vague where concern (ii) is supported; not comparable or not assessable with the reason. A conflicted
justification and a refuted declared necessity are not stated: E has no claim that challenges a purpose, and D states
no necessity.

The expectation stage (`skuld expect`) infers what each practice can be expected to serve and need without anything
the provider says. One batch per episode holds the practices that occurred in it, the episode's screens and
documentation from the corpus; screens Ratatoskr's notice classifier takes for consent dialogs or privacy notices are
left out, and the sample records which. The context's check refuses any part from D's report or a notice screen. An
answer that leaves a practice without a purpose, names a practice or component not in the batch, or cites what the
context does not hold is asked once more with the refusal (s<seed>/a2/; asked again and accepted at once, the retry
is removed); offline, the last kept attempt stands. The answers become Purpose and Dependency claims under E's status
rules: a purpose is supported only if it is specific and a screen or passage shows its outcome, what the processing is
for (the practice gives its action and object; citing the practice for the outcome does not count, since that the
processing happens shows nothing of what it is for), its beneficiary (the user, the provider or another party) and
context qualifying it; a Dependency claim has one value (essential, quality dependent, or not dependent, which only a
run supports), no dependency identified makes no claim, and a step that cites a practice as a reason it is needed is
dropped. Alternatives are the reasoning tier's. `skuld assess` reads the kept samples and asks no model, and fails if a stage-1 sample
or claim reaches anything of D's.

The assessment stage's reasoning tier (`skuld judge`) reads the expectation stage's claims, combined across samples
(purposes aligned by node and beneficiary within a practice), as hypotheses, and D's declared purposes as
declarations, marked as such; the check refuses any other part of D's report. It asks three questions. Specificity:
D's purpose statements in batches of twenty, each quoted with its sentence, against the norms on specific purposes;
a statement judged not specific, its action, object or outcome lacking, by steps citing it and a norm, is concern
(ii). Compatibility: per practice and supported inferred purpose that no specified purpose of its data covers (the
same DPV node or one above, not the root), one question listing those specified purposes, answered per pair by the
frame's factors; a step citing a declaration cannot make a purpose compatible and is dropped. A purpose no specified
purpose covers is concern (iii): supported by the rule tier where none is declared for its data, else by the reasoning
tier where it is judged not compatible with every one that is. Minimisation: per practice with a supported purpose,
its components, documentation and norms; an alternative technically supported by a cited document is concern (v).
The samples' judgements and Alternative claims are combined like every claim: one that a document supports decides
over samples that name no concern, and the disagreement raises the concern's uncertainty. The norms and guidelines are passages in `corpus/norms/`,
retrieved by requirement, kept apart so that the expectation stage's corpus digest does not change with them.

Experiments are a channel of the assessment stage. `skuld assess` reads the case report's measurements (`report.json`,
by digest) and makes the experimental channel's claims by its status rule (`rules.py`): from the removal of a
component one Dependency claim with its value, from each alternative an Alternative claim, demonstrated where the
comparison preserves the purpose. They are claims of every practice whose component a case varies: a datum's removal or
precision the practices of that datum or one below it, a recipient's removal the transmissions to it. A practice's
hypothesis purpose aligns with the case purpose of its beneficiary whose node is its own or the nearest above (≈),
and each experiment's claim is combined with the hypotheses of aligned purposes, a comparison deciding by its
strength; where no hypothesis aligns, reasoning is silent and the comparison stands alone. A demonstrated alternative
for an aligned case purpose is concern (v), whose O–E relation reads the run. `skuld select` chooses the experiments
the assessment asks for: per practice and supported purpose whose minimisation neither a document nor an experiment
decides, and on which Skuld can impose an alternative; those `inputs/chosen.yaml` names first (pursued by the author,
or in the calibration sample), then the rest within config.json's budget of device time (`experiments`, 0 by default:
off). `skuld propose --selection inputs/selection.json` writes cases only for what was chosen.

```bash
skuld propose <Loki exploration> --pilot <pilot> # generate and fix the inputs (or --workspace <folder>)
skuld catalogue                                  # the catalogue's families, reviewed or not
skuld freeze <workspace> --author "…"            # fix inputs written by hand before the runs
skuld run <workspace> --recorded <Loki run> --config loki.yaml --device emulator-5554 \
    --conditions baseline A1 A2 --repeat 3       # the replays, in rotated order
skuld change <workspace> oracles/O@1.yaml --reason "…"   # a later change, recorded
skuld analyse <workspace> [--offline]            # --offline: existing observation reports only
skuld describe <workspace> --package … --version … --observation <report>[=<run>] … [--declaration …] [--exploration …]
skuld expect <workspace>                         # the expectation stage's samples (seeds from config.json); --offline
skuld judge <workspace> [--question …]           # the reasoning tier's samples (seeds from config.json); --offline
skuld assess <workspace>                         # subjects, rule tier and both stages' kept samples, no model asked
skuld select <workspace> [--replace]             # the experiments the assessment asks for, within the budget
skuld check <workspace>                          # digests, pointers and replay of assessment.json (and report.json)
# propose, expect, judge, assess and check take --registry <file>; give all the same one, or none (Ratatoskr's built one)
skuld corpus check                               # passages without source, date or a person's check
skuld corpus coverage <reports or folders>       # recipients and data of O's reports no passage covers
```

`skuld propose` is the generator. Every episode of Loki's exploration (pseudo-saturation regime) that Loki's verifier
judged carried out yields up to three features (a first run's onboarding and the main feature it ends at, say), each
entered in the state the exploration reached before the episode and following the episode's actions, so that replays
of the one recording serve every case. The model (`config.json`'s, `gemma4:31b`, the stages') is given the flow
(the explorer's task, the verifier's reading, the screens) and the catalogue, and names a family of the catalogue or
describes a new one, filling the slots of its oracle templates from the screens. The answer is checked: known families
and predicates; text slots shown at the flow's end and not at its start; screen slots reached after its start;
requirements that name no datum of the search space and no identifier. A refused answer is asked once more with the
refusal; then the features that pass are kept and the others recorded with why. The launch is filled by rule. The
search space is derived from O's claims in the episode (`skuld/space.py`): per hooked identifier read, its replacement
by a constant; per location read, rounding to one and to no decimal; per recipient the registry resolves to an entity
not the provider's, blocking its domains (whose it is, `parties.py` decides as for the assessment's practices: by the
register entity, else by the domain; `--registry` as for `assess`). Conditions are named by their intervention, so cases share their runs.
Inputs are fixed with the model, the generator and the family as their author.

The catalogue (`catalogue/families/<id>@<version>.yaml`, local and ignored by git until it is deployed) holds the
families: a description of entry, path and outcome, purposes with requirements, and oracle templates whose arguments
name slots (`text`, `screen`, `activity`; `path_start` and `path_end` filled by every instantiation). A family is never
changed; a change is its next version. `skuld/catalogue.py` describes the format.

`skuld run` writes a Loki configuration per condition into `configs/` (every source Loki can hook set
to `pass`, except those the condition's alternative changes, and the hosts it blocks), calls
`loki -c … replay … --force` through `uv run --project ../Loki`, starts and stops frida-server
through Loki where the configuration instruments the app, and appends each run to `runs.jsonl`. It
refuses to run before the inputs are fixed. With `--qualify`, the cases the first baseline replay does not qualify (it
departs within their path, or one of their oracles is not met) are recorded in `qualification.json` and get a gap in
the report; the series stops only if no case qualified.

`skuld propose`, `skuld expect` and `skuld judge` reach the model through Ratatoskr (`pip install -e ".[reason]"`), with the API's
settings (`OLLAMA_BASE_URL`, `OLLAMA_API_KEY`) from the environment or Skuld's `.env`. A sample is not
asked again while its context, prompt, model and options are unchanged; the analysis reads only the
samples kept, so it needs no model. The corpus of documentation is `corpus/`, one passage per file, each with
`verified: {by, date}` once a person has checked it against its source.

The analysis takes the runs of each case's feature made after its inputs were fixed; the baseline
configuration from O's claims of the baseline runs; verifies every run under an alternative through O's report alone
(the hooked source handed the app the imposed value, no transmission to a removed recipient, the identifier sources
that could stand in for a removed one, and what no hook covers as unverifiable; Loki's status per hook and the
capture's connections per host from the report's scope);
applies the oracles; forms the comparisons; and records, per component, whether it is one of the baseline and, per
purpose and alternative, why none was compared. The case report makes no claim: the assessment reads its
measurements. The combination relates claims of aligned purposes: agreeing ones corroborate, and in a disagreement
the claim of greatest strength decides. The modules that write a status (`rules.py`, `combine.py`, `expectation.py`'s
and `judge.py`'s readings, `transparency.py`, `concerns.py`) call no model; only `ask.py` does, for `skuld propose`,
`expect` and `judge`.

The run folder itself:

```python
from skuld.runs import RunRefused, load

run = load("../Loki/runs/com.example.app/<run id>")  # RunRefused if Skuld cannot rely on it
run.actions  # what was done to the app, Loki's 'action' events
run.source_reads  # what the app read of an instrumented source, and what it was handed
run.changes  # source settings changed during the run, with their times
run.messages  # the captured HTTP messages (captured_http_message)
run.connections  # the captured connections (captured_connection)
run.verified  # Loki's verification of the instrumentation; run.verification has the details
run.scans  # by package: the permissions an app requests and its tracker libraries (if the run exported scans)
```

A run is refused (`RunRefused.reason`) if the folder is not a run (`not_a_run`), its record is of a
version Skuld does not read (`unsupported_version`), it did not end in order (`unfinished`), was not
captured or its capture failed (`no_capture`, `capture_failed`; `load(…, capture=False)` does not
read the capture), Loki did not validate its export (`export_not_validated`), the export is not
complete (`incomplete_export`), or its instrumentation record or its scans do not conform to
Ratatoskr's schemas (`invalid_record`), which Skuld checks again itself.

## Tests

```bash
pytest
ruff format . && ruff check .
```

One test reads a real run of Loki: `SKULD_RUN_DIR`, or the latest captured and instrumented run in
the sibling `Loki/runs/`. Another analyses the dry run's workspace (`SKULD_DRY_RUN`, or
`cases/pilatesworkout.yogaworkout.loseweight.workoutapps@1.6.4`) and checks the claims of the E
report's worked example; the three fixtures' assessments are rebuilt and checked. Each is skipped if its data is not
there. Earlier copies of the Pilates workspace are in `cases/archive/`.

## Documentation

| Document | Content |
|---|---|
| [docs/architecture.md](docs/architecture.md) | What Skuld is after the rewiring, how it uses Loki, how it reads a run folder |
| [`plan/6_skuld_plan.md`](../plan/6_skuld_plan.md) | Implementation plan of the whole component |
| [`LOKI_SKULD_REWIRE.md`](../LOKI_SKULD_REWIRE.md) | Why the capture and the instrumentation moved to Loki, and what Skuld is then |
| [`Loki/docs/capture.md`](../Loki/docs/capture.md) | The capture of a run, which Skuld reads |
| [`Loki/docs/instrumentation.md`](../Loki/docs/instrumentation.md) | The instrumentation of a run, its record and verification, which Skuld reads |

## License

GPL-3.0-only, see [LICENSE](LICENSE).
