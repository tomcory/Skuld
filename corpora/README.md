# Earlier corpora

A workspace names its corpus by path and digest (`assessment.yaml`, `corpus: {path, sha256}`) and refuses to load if
the corpus at that path has another digest. When `corpus/` changes, the earlier corpus is kept here, under the first
eight characters of its digest, so that the workspaces that name it still load and rebuild.

| Folder | Digest | Used by | Replaced on |
|---|---|---|---|
| `cd73311d/` | `cd73311d21b7f8da0844c901cf06b8274d362a3d76a0bd2eac36be57894d1393` | the Expectation paper's study (`expectation-paper/study-2026-11/`), Skuld's fixtures (`cases/`, now `workspaces/`) and their archives: 285 workspaces | 2026-11-18 |
| `954c86d9/` | `954c86d9249e…` (documentation; norms `34cad858…`) | no workspace (the study and the fixtures name `cd73311d`) | 2026-11-21 |
| `8b67a0e3/` | `8b67a0e3…` (documentation; norms `98296e4f…`) | no workspace | 2026-11-21 (second round) |
| `66765762/` | `66765762…` (documentation; norms `11042ea1…`) | no workspace | 2026-11-21 (facts) |

`cd73311d/` holds the four platform and component passages as committed before 2026-11-18 (from git) and a copy of
`norms/`, unchanged; its digest was checked equal to the one the workspaces name. The 285 workspaces had their
`corpus.path` rewritten to it on 2026-11-18 and nothing else; `cd73311d-repointed.tsv` lists each of them with the path
it had before. 141 of them, backup copies moved one folder deeper (`_before-*`, `archive*`), already pointed to no
corpus, and their other relative paths are broken as well; the 144 others load with every digest checked.

# The passages adopted on 2026-11-18

The corpus's platform and component passages, quoted verbatim from their sources for gate (c) of the Expectation report
0.9 (`ODE/expectation/expectation.tex`, `def:status`): a documented alternative is supported only by a passage checked
against its source. Drafted in `corpus/drafts/` (since removed), checked against their sources by Thomas Cory on
2026-11-18 (`verified`), and moved into `corpus/`, whose digest is now `954c86d9…`.

Every excerpt was checked twice by script against the pages as fetched on 18 Nov: once against the page text
extracted block by block, and once, sentence by sentence, against the raw HTML with tags stripped. Both find every
sentence verbatim; the only liberties are the source's headings set as sentences (Targeting., App analytics.,
Approximate., …), which the second check lists, and the manifest example's comments set after the permission they
annotate. Neither check is the person's check that gate (c) asks for, which the `verified` records state.

| Passage | Replaces | Source | What changed |
|---|---|---|---|
| `android-identifiers-principles.yaml` | `android-unique-identifiers.yaml` | developer.android.com/identity/user-data-ids | Verbatim; says "Only use an Advertising ID for user profiling or ads use cases", which the paraphrase left out |
| `android-identifiers-ads.yaml` | (new) | same page | The ads use cases: the Advertising ID is mandatory for ads, measurement, conversions, remarketing, ad fraud |
| `android-identifiers-analytics.yaml` | (new) | same page | Analytics, crash reporting, app testing: App set ID or FID |
| `android-advertising-id.yaml` | `android-advertising-id.yaml` | Play Console Help 6048248 | Verbatim instead of our own words; adds "For essential non ads use-cases such as analytics and fraud prevention, use App Set ID" |
| `android-id.yaml` | (new) | developer.android.com/reference/android/provider/Settings.Secure | Names the Android ID: unique per signing key, user and device; may change on a factory reset or a signing-key change |
| `android-id-reinstall.yaml` | (new) | developer.android.com/about/versions/oreo/android-8.0-changes | The Android ID does not change on uninstall or reinstall |
| `android-location-permissions.yaml` | `android-location-permissions.yaml` | developer.android.com/…/location/permissions | Verbatim; the accuracy figures and "Your app should still work when the user grants only approximate location access" |
| `appsflyer.yaml` | `appsflyer.yaml` | appsflyer.com/glossary/mmp/ | The old URL (/glossary/mobile-measurement-partner/) is dead; verbatim; tagged with recipient types |

## How they were adopted

1. Open the source, compare the text, and correct anything that differs.
2. Decide the open choices in its comment (tags, licence).
3. Remove the `draft` field, add `verified: {by: <name>, date: <date>}`, and move the file to `corpus/`; delete the
   passage it replaces (`android-unique-identifiers.yaml` for the principles).

## Open choices

- **Licences.** Android Developers pages are, as far as known, CC BY 4.0 (the footer that says so is loaded by script
  and was not in the fetched page); the Play Console Help and AppsFlyer pages state none, so their excerpts rest on
  quotation for analysis (§ 51 UrhG).
- **Tags** (revised in the double-check). A tag says that the passage concerns the datum, since retrieval and gate (b)
  both read it so; each passage is tagged with what its excerpt names. The Android ID on
  `android-identifiers-principles` follows the criterion decided on 18 Nov and stated in `skuld/corpus.py`: a passage is
  tagged with each node it names or that a rule it states plainly covers, listed one by one and never through a parent.
  The page's rules cover the Android ID without naming it; `android-id` and `android-id-reinstall` name it. `appsflyer`
  has no data node (a tag on `device-or-other-ids` gave it to every identifier practice) and `recipient_types:
  [analytics, advertising]`, which gate (b) reads for a recipient (`Passage.concerns`). `location.coordinates` needs no
  tag of its own, since it lies below `location.precise-location`.
- **AppsFlyer's excerpt** now includes the sentence that "This is done using …" refers to; the page spells
  "post-intall".
- **AppsFlyer's page is AppsFlyer's account of its own service**, i.e. the recipient's justification, not the
  provider's (review point 14 on independence).

## A retrieval problem found while drafting (resolved on 18 Nov 2026)

`Corpus.about` returns at most `PER_COMPONENT = 3` passages per component, in file order. Simulated with these drafts
and `asgard-data`: an advertising-ID practice receives `android-advertising-id`, `android-identifiers-ads` and
`android-identifiers-principles`; an Android ID practice the principles; an installation ID the analytics passage and
the principles; coordinates or a city the location passage; an IP address nothing. A practice sent to AppsFlyer never
receives `appsflyer.yaml`, which sorts last, not even where its datum is unidentified (`device-or-other-ids`), since the
datum's passages fill the three places first. Passages about the component's recipient should not compete with those
about its datum for the same three places. Resolved the same day: where a practice finds more than three passages,
`Corpus.about` gives up to three about the recipient's entity and up to three about the datum's node
(`skuld/corpus.py`).

# The passages adopted on 2026-11-21

Nineteen passages (ten norms, nine of documentation) drafted, re-verified and reviewed independently three times on
21 Nov, then adopted by the author: the record, with what each passage answers, what was left out, the checks, the
known limits of tagging and retrieval, and the decisions still open, is `adoption-2026-11-21.md`. After the second round of the same day (see the record) the
corpus's digests are `66765762…` (documentation) and `11042ea1…` (norms); after the facts (third round)
`b6aba7cf…` and `11042ea1…`.
