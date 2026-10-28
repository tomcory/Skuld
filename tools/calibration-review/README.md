# Calibration review (local)

A small web tool for the expert's blind review of a calibration sample of E's assessments (EV-E9), after Urda's label
review: an Express server that stores every decision as JSON, and a Vue page, without a build step.

```bash
skuld calibrate draw calibration/<id> <workspace>…   # draw and fix the sample
cd tools/calibration-review
npm install
npm start -- ../../calibration/<id>                   # http://localhost:3001 (PORT to change it)
skuld calibrate score calibration/<id>                # error rates from the decisions so far
```

The server reads the sample's `sample.json` and the collections' documents in `documents/`; it never serves `key.json`,
which holds E's outcomes, so the review is blind. Decisions go to the sample's `reviews.json`, keyed by item id; the
position is kept in `review-position.json`, and `?item=<n>` opens the n-th item.

Each item is one requirement of the frame for one subject of an application: its collection of documents, a purpose
statement it declares (highlighted in the policy), or a practice observed in a run with one purpose it serves. The page
shows the requirement, the question for its step, the subject, and the collection's documents (a document D could not
analyse is marked). For a practice it also shows what the expectation stage read with it: the screens of the episodes
it was observed in and the documentation passages of its components and data, each once, but not the stage's answer;
the section is shown or hidden with C, and the browser remembers the choice. A decision is one of:

| Decision | Meaning | Key |
|---|---|---|
| fails | the subject fails the requirement as the question asks: a concern | F |
| holds | it does not | H |
| unsure | cannot be decided from what is shown; left out of the scores | U |

← → move between items, O jumps to the next item without a decision, / searches the document. A note is saved with the
decision.
