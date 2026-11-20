# Calibration review (local)

The tool serves three kinds of sample: the **review of aggregated concerns** (`skuld review draw`, the expectation
paper's evaluation since 12 Nov 2026; first section), the **review of the expectation stage's predictions**
(`skuld review expect-draw`) and the **blind calibration** (`skuld calibrate draw`, EV-E9; the rest of this README).
It tells them apart by `sample.json`'s `kind` (`aggregate-review`, `expectation-review`, none for a calibration) and
serves each its own page in `public/`.

## Review of aggregated concerns

A non-blind verification of E's output by two reviewers working independently, blind to the model run
(`Skuld/skuld/review.py` says how; the design is in `expectation-paper/aggregator_plan.md`, "Review design"):

```bash
skuld aggregate <workspace>                                     # every workspace: aggregate.json
skuld review draw reviews/<id> <workspaces of every run>…       # --per-run (70, proportional), --per-stratum, --anchor, --seed
cp -r reviews/<id> reviews/<id>-a; cp -r reviews/<id> reviews/<id>-b   # one copy per reviewer
npm start -- ../../reviews/<id>-a                               # http://localhost:3001
skuld review agree reviews/<id> reviews/<id>-a/reviews.json reviews/<id>-b/reviews.json   # κ, disagreements
skuld review score reviews/<id>                                  # after adjudication: agreement, anchoring, misses
```

A unit is one aggregated concern in full: its statement (label, status, tier, uncertainty: its level and reasons), its members with their
reasons, E's purposes and alternatives, the evidence they rest on, and the application's documents. The reviewer
records, in order:

| Part | Values | Keys |
|---|---|---|
| Evidence exists and is cited correctly | yes, partly, no, none cited | 1–4 |
| E's conclusion follows from that evidence | yes, partly, no | Q W E |
| Each phrase (declared purposes only) | specific, not specific, unsure | N: all not specific |
| The verdict on the concern as stated, after the criteria (which explain it) | agree, disagree, unsure | A D U |

For declared purposes E holds not specific, the verdict is the phrases' (author, 12 Nov 2026): the server derives it
when the unit is saved (S): agree if every phrase judged is not specific, disagree if none is, partly if some are,
unsure if every phrase is unsure; it refuses a verdict sent for such a unit. Partly counts as not agreeing.

Units of **declared purposes** are judged blind first, phrase by phrase: the server serves only the unit's id,
requirement, question and phrases until every phrase is judged specific, not specific or unsure (N: all not specific; S:
save), and refuses any other part before then (409); the blind judgments go to `reviews.json` as `blind_phrases`, are
never changed or removed, and the non-blind phrases then start from them, with E's output shown and "your blind
judgment" under each phrase. `skuld review score` reports the blind phrases' agreement with E beside the non-blind
agreement on the same phrases and how many judgments changed once E was shown; `agree` gives their κ. Samples drawn
before 20 Nov 2026 carry no phrases and are reviewed as before.

Some other units are **shown blind first** (subject, question and documents only): the reviewer decides fails, holds or
unsure (F H U) before E's output is revealed; the server withholds the output until then, and a blind decision is never
changed or removed. Once every unit of an application is judged, the **recall pass** (R) lists its practices and
declared purposes for noting what E should have raised and did not; it is saved in `recall.json`. `key.json`, which
names each unit's run, is never served.

The evidence list names each item's source in words (`review.source`: the practice as observed, traffic as captured, a
screen of the app, the provider's documents, documentation or a legal norm from the corpus, E's expectation stage)
instead of E's item ids, and shows a text cited under several items once, with how many members cite it (author's
review of the dashboards, 13 Nov 2026). Traffic shows the value O found highlighted.

## Vocabularies in the pages

Both review pages show a unit's data types and purpose nodes in code type; a click opens the value in its vocabulary
(`public/vocab.js`, shared by the pages): a tree with the value selected and marked "shown in the unit", its path,
description, broader node, the nodes alongside it and the narrower ones, a filter, and a way back to the value. The
stage-1 page's DPV node fields (a missed purpose, a better node) suggest nodes while one types and open the same tree to
select one. The vocabularies travel in `sample.json` (`vocabularies: {purpose, data}`, written by both draws) and are
served at `/api/vocabulary?kind=purpose|data`, so the tool needs no network.

## A reviewer's package

`skuld review export <package.zip> <drawn sample folders…> --reviewer <id>` packs this tool (server, pages and only the
modules the server uses, ~3 MB zipped), the reviewer's copies of the samples (sample.json and documents; never key.json
or manifest.json; refused if sample.json or the sample folder's name names a run or model, or if the folder has no
manifest.json, so a reviewer's copy cannot be exported, only the drawn sample), launchers per sample
(`start-<sample>.command|.sh|.bat`, each serving its sample on its own port from http://localhost:3001),
`pack-reviews.command|.sh|.bat` and a guide (`README.md`). The reviewer needs only Node.js 18+. `skuld review import
<reviews-<id>.zip> <reviews folder>` files the returns into `<sample>-<id>/`, keeping an earlier return as
`<file>.<time>.bak` (with a counter where two imports fall in the same second). The import needs `<reviews
folder>/<sample>/sample.json`, skips macOS's `__MACOSX/` copies, takes a zip packed flat only for a one-sample package,
and reports, without refusing, unknown item ids and `reviewed` times that are malformed or outside the review period.

`score` weights each stratum by its population over the units judged in it and gives the unweighted rate beside each
estimate; `agree` reports Cohen's κ, also without the unsure verdicts (`overall_without_unsure`).

The units are not shuffled but **interleaved by stratum** (`review.interleave`): each next place goes to the stratum
furthest behind its share of the drawn units, ties broken at random, each stratum's units in random order, so every
prefix of the order covers the strata in proportion (within one unit) and a partial return is itself a smaller
stratified sample, while the order says nothing usable of a unit's run. For a partial return `score` and `expect-score`
list per stratum the units drawn, reviewed and judged and the strata not reached: a stratum with no judged unit drops
out of the weighted rates, which then stand for the strata reached (`population_covered`).

The Windows launchers are generated and checked by a test on macOS (CRLF, ASCII, quoted paths, no Unix syntax, the
files they name present in an exported package); they have not been run on Windows. A sample folder's name must be
letters, digits, `-` or `_`.

## Review of the expectation stage's predictions

A sample of what E's first stage predicted per practice (`Skuld/skuld/review_expectation.py`; author, 12 Nov 2026),
reviewed before the aggregated concerns, whose units show the later reasoning:

```bash
skuld review expect-draw reviews/<id> <workspaces of every run>…        # --per-stratum (default 8; the study: 12), --per-app, --seed
cp -r reviews/<id> reviews/<id>-a; cp -r reviews/<id> reviews/<id>-b    # one copy per reviewer
npm start -- ../../reviews/<id>-a                                       # http://localhost:3001
skuld review expect-agree reviews/<id> reviews/<id>-a/reviews.json reviews/<id>-b/reviews.json
skuld review expect-score reviews/<id>                                   # after adjudication
```

A unit is one practice of one run: its purposes as the stage predicted them (combined over seeds), each with its
dependencies and their reasoning steps and cited texts, and on the right the context the stage read (the cited items
of the selected purpose, the episodes' screens, the corpus passages). The provider's documents are not shown: the stage
never sees them, and the predictions are judged against what it saw. Per purpose: plausible, DPV node (with a better
node), beneficiary, role, and for a supported purpose whether its citations show the outcome; per dependency the stage
stated: the relationship and the steps; per practice, the purposes missed (functional ones ticked) and a note. **Done**
(Enter) is accepted only once every question is answered; **Save** (S) keeps a unit half-done. The units are drawn per
run × role × status and never name the run. With `--per-app N` the draw takes about N units of an application per run
at most (in the study two applications had 18 and 15 of 66): the cap is shared over the run's strata by their sizes,
an application over its share is passed over within a stratum, and its units fill the stratum only where other
applications cannot, so stratum sizes and weights are unchanged; within a stratum the rate then leans towards the
average over applications. The manifest records each application's units and those drawn.

Each dependency is shown as a *need*: whether the data or the recipient (its component) is essential, quality-dependent
or not needed for the purpose. The parts a reasoning step cites are chips (traffic, screen, passage) that show their
text on click, so a message cited by several steps is not repeated. A need E holds not assessable is not asked; it says
why (for a purpose too vague: in every answer that states it; by E's combination, answers that cannot assess a need
abstain, so a need is not assessable only if none of its answers could judge it) and its reasoning opens on request.
Statuses read as E's ("E: supported"), with what they mean on hover.

## Blind calibration

A small web tool for the expert's blind review of a calibration sample of E's assessments (EV-E9), after Urda's label
review: an Express server that stores every decision as JSON, and Vue pages (`public/`), without a build step.

```bash
skuld calibrate draw calibration/<id> <workspace>…   # draw and fix the sample
cd tools/calibration-review
npm install
npm start -- ../../calibration/<id>                   # http://localhost:3001 (PORT to change it)
skuld calibrate score calibration/<id>                # error rates from the decisions so far
```

**Two reviewers.** Each reviews a copy of the sample folder of their own, independently, with the prior review hidden
(no `prior-review.json` in the copy). Then, with both reviews files at hand:

```bash
skuld calibrate agree calibration/<id> reviews-a.json reviews-b.json   # kappa, disagreements -> agreement.json
npm start -- ../../calibration/<id>                                    # O: the next item to adjudicate
skuld calibrate score calibration/<id>
```

`agree` seeds the sample's `reviews.json` with the decisions both made, if it has none yet, so the items left
undecided are the disagreements and the items either reviewer left open.

The server reads the sample's `sample.json` and the collections' documents in `documents/`; it never serves `key.json`,
which holds E's outcomes, so the review is blind. Decisions go to the sample's `reviews.json`, keyed by item id; the
position is kept in `review-position.json`, and `?item=<n>` opens the n-th item.

Each item is one requirement of the frame for one subject of an application: its collection of documents, a purpose
statement it declares (highlighted in the policy), or a practice observed in a run with one purpose it serves. The page
shows the requirement, the question for its step, the subject, and the collection's documents (a document D could not
analyse is marked). For a practice it also shows what the expectation stage read with it: the screens of the episodes
it was observed in and the documentation passages of its components and data, each once, but not the stage's answer;
the section is shown or hidden with C, and the browser remembers the choice.

Where the sample folder has a `prior-review.json`, each item also shows its **prior review**: another reviewer's
decision and note, with who made it and when; it is never E's outcome, which stays in `key.json`. P shows or hides
it, remembered like C. `prior-review.json`'s form:

```json
{"reviewer": "…", "reviewed": "2026-10-29", "items": {"u001": {"decision": "holds", "note": "…"}}}
```

The scores read `reviews.json` only, which the tool writes keyed by item id (`calibrate` reads either form):

```json
{"u001": {"decision": "holds", "note": "…", "reviewed": "2026-10-29T14:03:12.000Z"}}
```

A decision is one of:

| Decision | Meaning | Key |
|---|---|---|
| fails | the subject fails the requirement as the question asks: a concern | F |
| holds | it does not | H |
| unsure | cannot be decided from what is shown; left out of the scores | U |

On the first visit a tour highlights each part of the page in turn and explains it (Back, Next, Skip; ← →, Enter, Esc);
**Tour** in the header starts it again. ← → move between items, O jumps to the next item without a decision, / searches
the document. A note is saved with the decision.
