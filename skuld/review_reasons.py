"""
The reasons a reviewer names for an answer short of a plain yes (author, 24 Nov 2026): every question that offers
`partly` also offers `mostly`, and both name one or more reasons from a list tailored to the question, picked, never
typed, or `Other`, which asks for the reviewer's own reason in a few words. The study's reviewers found `partly` too
broad: it stood both for "almost there" and for "a little bit". The level says how far an answer is from a plain yes;
the reasons say why.

A review's answers keep a question's reasons as `<question>_reasons` (ids) and the written one as `<question>_other`.
The sample carries the lists (`questions(...)`), so that the review tool shows and checks the ones the sample was drawn
with.
"""

#: The reason that is written, not picked
OTHER = ("other", "Other", "another reason: say which in the field that opens")
WHEN = ("mostly", "partly")


def _table(*options) -> dict:
    return {"when": WHEN, "options": (*options, OTHER), "free": OTHER[0]}


#: The review of stage 1 (skuld.review_expectation): per purpose, plausible and cites; per need, relationship, steps
STAGE_ONE = {
    "plausible": _table(
        (
            "overstates",
            "Overstates",
            "asserts a detail the context does not show (personalised ads where only ad delivery is shown)",
        ),
        ("vague", "Too vague", "too broad or too generic to say what the recipient does"),
        ("bundles", "Bundles purposes", "puts two or more purposes into one (analytics and advertising)"),
        ("part_of_flow", "Part of the flow", "explains only part of what the flow sends or to whom"),
        ("loose_fit", "Loose fit", "the recipient could do this, but the flow gives little sign of it"),
    ),
    "cites": _table(
        (
            "broader",
            "Only the broader activity",
            "the parts show the activity (ads appear), not what sets this purpose apart (that they are personalised)",
        ),
        ("some_parts", "Not all parts", "some cited parts show the outcome, others do not"),
        ("indirect", "Only indirectly", "the parts suggest the outcome but do not show it happening in this app"),
        ("generic", "Generic source", "a guideline or documentation passage, not something of this app"),
    ),
    "relationship": _table(
        ("overstated", "Need overstated", "stronger than the flow warrants (essential where quality-dependent fits)"),
        ("understated", "Need understated", "weaker than the flow warrants (not needed where it is quality-dependent)"),
        ("wrong_component", "Wrong component", "the need holds for the data but not the recipient, or the reverse"),
        ("partial", "Only for part of the flow", "holds for some of what is sent, or for some recipients, not all"),
    ),
    "steps": _table(
        ("uncited", "Uncited claim", "a step claims something about this app or recipient without citing anything"),
        ("contradicts", "Contradicts its citation", "a step says something its cited part does not, or the reverse"),
        ("leap", "Leap", "the conclusion does not follow from the steps, even where each step holds"),
        ("wrong_cite", "Cites the wrong part", "the claim may hold, but the part it cites is not about it"),
    ),
}

#: The review of aggregated concerns (skuld.review): the two criteria before the verdict
CONCERNS = {
    "evidence": _table(
        ("not_said", "Item does not say it", "an item exists but does not say what E takes it to say"),
        ("fragmented", "Fragmented", "one sentence cut into fragments that are counted as separate evidence"),
        ("wrong_item", "Wrong item", "an item about another practice, recipient or application"),
        ("missing", "Key item missing", "the conclusion needs an item E does not cite"),
    ),
    "follows": _table(
        ("overreach", "Overreaches", "the conclusion is stronger than the evidence supports"),
        ("gap", "Gap in reasoning", "a step between the evidence and the conclusion is missing"),
        ("contrary", "Ignores contrary evidence", "something in the evidence or the documents points the other way"),
        ("condition", "Unstated condition", "it holds only under a condition E does not state"),
    ),
}

#: Per question, its answers in order, best first (unsure and none cited left out): their agreement is also weighted,
#: and their rate also given leniently, counting yes and mostly as agreeing
ORDERED = {q: ("yes", "mostly", "partly", "no") for q in (*STAGE_ONE, *CONCERNS)}


def reasons_key(question: str) -> str:
    """Where an answer keeps a question's reasons: `<question>_reasons`."""
    return f"{question}_reasons"


def other_key(question: str) -> str:
    """Where an answer keeps the text of a question's written reason (Other): `<question>_other`."""
    return f"{question}_other"


def questions(table: dict) -> dict:
    """The lists as a sample carries them, for the review tool."""
    return {
        q: {
            "when": list(r["when"]),
            "options": [{"id": i, "label": label, "hint": hint} for i, label, hint in r["options"]],
            "free": r["free"],
        }
        for q, r in table.items()
    }


def problem(question: str, answers: dict, table: dict) -> str | None:
    """What keeps a question's reasons from being complete: none named, one not in the list, or Other without its
    text; None where its answer names no reasons or they are complete."""
    r = table.get(question)
    if not r or answers.get(question) not in r["when"]:
        return None
    named = answers.get(reasons_key(question)) or []
    if not named or not set(named) <= {i for i, *_ in r["options"]}:
        return "reasons"
    if r["free"] in named and not str(answers.get(other_key(question)) or "").strip():
        return "other reason"
    return None


def tally(question: str, answers: dict, table: dict, counts, others: list, where: dict) -> None:
    """Counts an answer's reasons into `counts` as `<answer>:<reason>` and appends its written reason to `others`."""
    r = table.get(question)
    answer = answers.get(question)
    if not r or answer not in r["when"]:
        return
    for reason in answers.get(reasons_key(question)) or []:
        counts[f"{answer}:{reason}"] += 1
        if reason == r["free"] and str(answers.get(other_key(question)) or "").strip():
            others.append({**where, "answer": answer, "text": answers[other_key(question)].strip()})
