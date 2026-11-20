"""
E's relations to its expectation, pass-through and open conditions.

O–E, by rule, per practice, supported Purpose claim, question and component (data or recipient), over E's combined
claims; a relation names the claims it reads in `to`, and its outcome is a function of them (`outcome`):

    dependency    the Dependency claims on the component for the purpose (the hypotheses', and the experiments' for a
                  case purpose ≈ it), decided by the combination's rule: functional (data) or recipient dependency
                  supported if the deciding claim supports essential or quality_dependent; no functional dependency
                  established, or recipient dependency not established, otherwise; conflicting if the claims of
                  greatest strength disagree, not assessable if every claim is
    minimisation  the Alternative claims on the component for the purpose: an alternative demonstrated if one is
                  supported at that level, else technically supported if one is at that level; else insufficient
                  evidence (a plausible alternative, or one refuted, has no outcome of its own), not assessable if
                  every claim is

The outcome carries the deciding claim's level and strength, so that what documents describe is not read as what a
run measured. A practice none of whose Purpose claims is supported has one relation, insufficient evidence, to them,
as has a supported Purpose claim no claim of a question names. An experiment's claims for a case purpose no Purpose
claim aligns with (reasoning is silent on it) are related per that case purpose.

D–E, by rule, per declared purpose, against E's Purpose claims for the practices of its data (its data or data below
it) that its node covers (the node or one above it, as for purpose limitation):

    not_comparable               O's and D's scopes are not, or the purpose or its data is no node of the vocabularies
    purpose_too_vague            concern (ii) is supported for a statement of it
    not_assessable               no practice of its data is observed, or E's Purpose claims for all of them are not
                                 assessable
    justification_supported      every practice of its data that E formed an expectation of has a supported Purpose
                                 claim it covers; partially if some do; not established if none does

and per declared strict necessity, a legal basis of Art. 6(1)(b) (processing necessary for a contract with the data
subject), against the experiments' claims for the practices of its data:

    declared_necessity_refuted   a run shows a user's purpose achieved without it: a not-dependent Dependency claim or a
                                 demonstrated Alternative claim, supported at strength run, for a case purpose of the
                                 user; holds for the features the case report covers (an open condition)
    not_comparable               it is declared for no data in particular (the root), as a list of the bases a policy may
                                 use is, which no practice can refute

A necessity is never supported (E's asymmetry); where no run refutes it, the claim is passed on with the reason. Not
stated: a conflicted justification, since no channel of the instance refutes a Purpose claim (whether a provider's purpose
is achieved is decided on its servers, observability E3).

Pass-through: every claim of O's and D's reports passed on to the Investigator by reference (report digest and claim
id, or JSON pointer for D's claims), with the relations it takes part in or the reason it has none. A claim passed on
is not copied: the Investigator reads it in the report it names, so the claims keep one source.
"""

from ratatoskr import align
from ratatoskr.vocabularies import Vocabulary

from skuld import combine, parties
from skuld.assessment import Subjects, at
from skuld.common import DATA, vocabulary
from skuld.correspondence import Relation, covered
from skuld.inputs import ReportRef
from skuld.observe import claims as o_claims
from skuld.transparency import INCOMPLETE, MISSING_IF, UNREAD, Status

#: 8: a recipient D names is the provider's own by its owner when D's documents were collected (20 Nov 2026);
#: 7: D–E: a purpose, or its data, D could not place (Urda 2.1.0) is not comparable as such; 6: claims of practices
#: left out for an unknown datum are passed on as such
VERSION = "8"
COMPONENT = {"role": "method", "id": "skuld.relations", "version": VERSION}

CONFLICTING, INSUFFICIENT, NOT_ASSESSABLE, NOT_COMPARABLE = (
    "conflicting",
    "insufficient_evidence",
    "not_assessable",
    "not_comparable",
)
DEPENDENCY = {
    ("data", True): "functional_dependency_supported",
    ("data", False): "no_functional_dependency_established",
    ("recipient", True): "recipient_dependency_supported",
    ("recipient", False): "recipient_dependency_not_established",
}
ALTERNATIVE = {"demonstrated": "alternative_demonstrated", "technically_supported": "alternative_technically_supported"}
SUPPORTED, PARTIALLY, NOT_ESTABLISHED, TOO_VAGUE = (
    "justification_supported",
    "justification_partially_supported",
    "justification_not_established",
    "purpose_too_vague",
)
#: A declared strict necessity refuted: Art. 6(1)(b), processing necessary for a contract with the data subject, for data
#: whose removal a run shows the user's purposes not to depend on
NECESSITY_REFUTED = "declared_necessity_refuted"
#: The legal basis that declares processing necessary: for the performance of a contract with the data subject
CONTRACT = "GDPR-6-1-b"
#: Why a claim of D has no relation, by its type
UNRELATED = {
    "declares_legal_basis": "E forms no expectation of legal bases; a declared necessity it relates only where a run refutes it",
    "declares_retention": "E relates no declared retention",
    "declares_transfer": "E relates no declared transfers",
}
#: The values of a Dependency claim that state a functional dependency
DEPENDS = ("essential", "quality_dependent")


def e_ref(claim_id: str) -> dict:
    """A claim of E's own report, as a relation names it."""
    return {"dimension": "E", "claim": claim_id}


def outcome(aspect: str, claims: list[dict]) -> tuple[str, dict | None]:
    """The O–E outcome for a component from the claims a relation reads (all Dependency or all Alternative claims),
    and the claim that decides it."""
    if not claims:
        return INSUFFICIENT, None
    if all(c["status"] == "not_assessable" for c in claims):
        return NOT_ASSESSABLE, None
    if claims[0]["type"] == "dependency":
        status, decider = combine.decide(claims)
        if status == "conflicted":
            return CONFLICTING, None
        depends = status == "supported" and decider.get("relationship") in DEPENDS
        return DEPENDENCY[(aspect, depends)], decider if status in combine.DECISIVE else None
    if any(c["status"] == "conflicted" for c in claims):
        return CONFLICTING, None
    for level in ("demonstrated", "technically_supported"):
        found = [c for c in claims if c.get("level") == level and c["status"] == "supported"]
        if found:
            return ALTERNATIVE[level], max(found, key=lambda c: combine.STRENGTH[c.get("strength", "own")])
    return INSUFFICIENT, None


def o_e(subjects: Subjects, hypotheses: list[dict], alternatives: list[dict], tested: list[dict]) -> list[Relation]:
    """The O–E relations: per practice E formed an expectation of."""
    out: list[Relation] = []

    def add(p, aspect: str | None, read: list[dict], found: str, reason: str | None = None) -> None:
        out.append(
            Relation(
                id="",
                type="O-E",
                tier="rule",
                outcome=found,
                of=p.claims[0],
                to=[e_ref(c["id"]) for c in read],
                subject=p.id,
                aspect=aspect,
                reason=reason,
            )
        )

    def relate(p, questions: dict[tuple, list[dict]]) -> int:
        n = 0
        for (_, aspect), claims in questions.items():
            if claims:
                add(p, aspect, claims, outcome(aspect, claims)[0])
                n += 1
        return n

    for p in subjects.practices:
        purposes = [h for h in hypotheses if h["subject"] == p.id and h["type"] == "purpose"]
        supported = [h for h in purposes if h["status"] == "supported"]
        if purposes and not supported:
            add(p, None, purposes, INSUFFICIENT, "no purpose of the expectation stage is supported")
        for h in supported:
            questions = {}
            for aspect in ("data", "recipient"):
                component = f"{p.id}.{aspect}"
                mine = [x for x in tested if h["id"] in x["basis"] and x["component"] == component]
                combined_in = {m for x in mine for m in x["of"]}
                questions[("dependency", aspect)] = [x for x in mine if x["type"] == "dependency"] + [
                    c
                    for c in hypotheses
                    if c["type"] == "dependency"
                    and c.get("basis") == [h["id"]]
                    and c["component"] == component
                    and c["id"] not in combined_in
                ]
                questions[("minimisation", aspect)] = [
                    c for c in alternatives if c["basis"] == [h["id"]] and c["component"] == component
                ] + [x for x in mine if x["type"] == "alternative"]
            if not relate(p, questions):
                add(p, None, [h], INSUFFICIENT, "no claim of dependency or alternative names the purpose")
        alone: dict[str, dict[tuple, list[dict]]] = {}
        for x in tested:
            if x["subject"] == p.id and not x["basis"]:
                question = "dependency" if x["type"] == "dependency" else "minimisation"
                key = (question, x["component"].rsplit(".", 1)[1])
                alone.setdefault(f"{x['case']}/{x['purpose']['id']}", {}).setdefault(key, []).append(x)
        for questions in alone.values():
            relate(p, questions)
    return out


def d_e(
    subjects: Subjects,
    hypotheses: list[dict],
    vague: dict[str, str],
    data: Vocabulary,
    purposes: Vocabulary,
    tested: list[dict] = (),
) -> list[Relation]:
    """The D–E relations: per positive declared purpose, and per declared strict necessity. `vague` names the
    declarations of a statement concern (ii) supports, with the concern; `tested`, the experiments' combined claims."""
    out: list[Relation] = []
    comparable = subjects.comparability.get("comparable") is not False

    def add(**kwargs) -> Relation:
        relation = Relation(id="", type="D-E", tier="rule", **kwargs)
        out.append(relation)
        return relation

    out += _necessity(subjects, tested, data, comparable)
    if not hypotheses:
        return out
    for d in subjects.declarations:
        if d.type != "declares_purpose" or d.polarity != "+":
            continue
        if not comparable:
            add(outcome=NOT_COMPARABLE, of=d.claim, subject=d.id, reason="O's and D's scopes are not comparable")
            continue
        marks = getattr(d, "unplaced", ())
        if ("purpose" in marks and d.value == purposes.root) or ("category" in marks and d.data == data.root):
            what = "the purpose" if "purpose" in marks and d.value == purposes.root else "the data it is declared for"
            add(outcome=NOT_COMPARABLE, of=d.claim, subject=d.id, reason=f"D could not place {what}")
            continue
        if not isinstance(d.value, str) or d.value not in purposes or d.value == purposes.root or d.data not in data:
            what = "its data" if isinstance(d.value, str) and d.value in purposes and d.value != purposes.root else "it"
            add(outcome=NOT_COMPARABLE, of=d.claim, subject=d.id, reason=f"{what} names no node E aligns by")
            continue
        if d.id in vague:
            add(outcome=TOO_VAGUE, of=d.claim, to=[e_ref(vague[d.id])], subject=d.id)
            continue
        practices = [
            p
            for p in subjects.practices
            if p.data in data and align.data(p.data, d.data, data).kind in (align.EQUAL, align.NARROWER)
        ]
        expected = {p.id: [h for h in hypotheses if h["subject"] == p.id and h["type"] == "purpose"] for p in practices}
        decidable = {i: hs for i, hs in expected.items() if any(h["status"] != "not_assessable" for h in hs)}
        if not decidable:
            reason = (
                "E's Purpose claims for every practice of its data are not assessable"
                if any(expected.values())
                else "no practice of its data that E formed an expectation of is observed"
            )
            add(outcome=NOT_ASSESSABLE, of=d.claim, subject=d.id, reason=reason)
            continue
        aligned = {
            i: [
                h["id"]
                for h in hs
                if h["status"] == "supported"
                and h["purpose"].get("node") in purposes
                and covered(h["purpose"]["node"], [d.value], purposes)
            ]
            for i, hs in decidable.items()
        }
        k = sum(1 for ids in aligned.values() if ids)
        found = SUPPORTED if k == len(decidable) else PARTIALLY if k else NOT_ESTABLISHED
        read = sorted({h for ids in aligned.values() for h in ids}) or sorted(
            {h["id"] for hs in decidable.values() for h in hs if h["status"] == "supported"}
        )
        add(
            outcome=found,
            of=d.claim,
            to=[e_ref(h) for h in read],
            subject=d.id,
            reason=f"{k} of {len(decidable)} practices of its data have a supported purpose it covers",
        )
    return out


def _necessity(subjects: Subjects, tested: list[dict], data: Vocabulary, comparable: bool) -> list[Relation]:
    """The D–E relations of declared strict necessity (Art. 6(1)(b)): refuted where a run shows a user's purpose
    achieved without the data; none where nothing refutes it."""
    out = []
    for d in subjects.declarations:
        if d.type != "declares_legal_basis" or d.polarity != "+" or d.value != CONTRACT:
            continue
        common = {"type": "D-E", "tier": "rule", "of": d.claim, "subject": d.id}
        if not comparable:
            out.append(
                Relation(id="", outcome=NOT_COMPARABLE, reason="O's and D's scopes are not comparable", **common)
            )
            continue
        if d.data == data.root or d.data not in data:
            reason = "it is declared for no data in particular, as a list of the bases a policy may use is"
            out.append(Relation(id="", outcome=NOT_COMPARABLE, reason=reason, **common))
            continue
        practices = {
            p.id
            for p in subjects.practices
            if p.data in data and align.data(p.data, d.data, data).kind in (align.EQUAL, align.NARROWER)
        }
        shown = [
            x
            for x in tested
            if x["subject"] in practices
            and x["status"] == "supported"
            and x.get("strength") == "run"
            and (x.get("purpose") or {}).get("beneficiary") == "user"
            and (
                (x["type"] == "dependency" and x.get("relationship") == "not_dependent")
                or (x["type"] == "alternative" and x.get("level") == "demonstrated")
            )
        ]
        if shown:
            cases = sorted({x.get("case") or "?" for x in shown})
            out.append(
                Relation(
                    id="",
                    outcome=NECESSITY_REFUTED,
                    to=[e_ref(x["id"]) for x in shown],
                    reason=f"a run shows the user's purposes of {', '.join(cases)} achieved without its data",
                    **common,
                )
            )
    return out


def _key(ref: dict) -> tuple:
    return ref["dimension"], ref["report"], ref["claim"]


def passed_on(
    subjects: Subjects,
    observations: list[ReportRef],
    declaration: ReportRef | None,
    relations: list[Relation],
    expected: bool = False,
    left_out: list = (),
) -> list[dict]:
    """Every top-level claim of O's reports and every claim of D's report, with its relations or why it has none;
    `expected` says whether E's expectation stage has claims, `left_out` the practices left out of the assessment
    because O could not identify their datum (`assessment.known_data_only`)."""
    related: dict[tuple, list[str]] = {}
    in_practice: dict[tuple, str] = {}
    for p in subjects.practices:
        for ref in p.claims:
            in_practice[_key(ref)] = p.id
    unknown_datum = {_key(ref) for p in left_out for ref in p.claims}
    for r in relations:
        for ref in [r.of, *r.to]:
            if ref["dimension"] in ("O", "D"):
                related.setdefault(_key(ref), []).append(r.id)
        if r.subject:  # a relation of a practice relates every claim the practice aggregates
            for p in subjects.practices:
                if p.id == r.subject:
                    for ref in p.claims:
                        related.setdefault(_key(ref), []).append(r.id)
    comparable = subjects.comparability.get("comparable") is not False
    out = []
    for report in observations:
        for claim in o_claims(report.load()):
            ref = {"dimension": "O", "report": report.sha256, "claim": claim["id"]}
            if _key(ref) in unknown_datum and _key(ref) not in related:
                reason = "left out: O could not identify its datum (source_not_analysable)"
                out.append({"claim": ref, "not_related": "not_assessable", "reason": reason})
                continue
            out.append(_entry(ref, related, in_practice, comparable, expected, "O"))
    for d in subjects.declarations:
        out.append(_entry(d.claim, related, in_practice, comparable, expected, "D", d))
    # D's findings go on to the Investigator by reference (DM9)
    for f in declaration.load().get("findings", []) if declaration else ():
        out.append({"finding": {"report": declaration.sha256, "finding": f["id"]}})
    return out


def from_declaration(
    declaration: ReportRef | None, subjects: Subjects, related: list[Relation], registry=None
) -> tuple[list[dict], list[dict]]:
    """D's open conditions: those E decides from O's practices and the parties (`decided`), and those it passes on to
    the Investigator by the condition they continue (`open`).

        collect  whether a policy's data leaves the device, which Google counts as collection: holds where O observed a
                 transmission of the data declared (its node or one below), by those practices and their O–D
                 relations; otherwise open, since O's not observing it is no absence
        share    whether a recipient receives data as a third party, which Google counts as sharing: fails where every
                 recipient it names is the provider's own (parties.relate), since no data goes to another company;
                 otherwise open, since whether a recipient acts as a service provider is a role no register states
    """
    if declaration is None:
        return [], []
    report = declaration.load()
    comparable = subjects.comparability.get("comparable") is not False
    declared = {d.claim["claim"]: d for d in subjects.declarations}
    provider = parties.controller(report, subjects.application)
    data = vocabulary(DATA)
    open_, decided = [], []
    for o in report.get("open", []):
        of = {"report": declaration.sha256, "open": o["id"]}
        named = [declared[c] for c in o["qualifies"] if c in declared and declared[c].channel != "data_safety"]
        outcome = None
        if comparable and o.get("predicate") == "collect":
            nodes = {d.data for d in named if d.type == "declares_collection"}
            shown = [
                p
                for p in subjects.practices
                if p.claim_type == "transmits"
                and any(align.data(p.data, n, data).kind in (align.EQUAL, align.NARROWER) for n in nodes)
            ]
            if shown:
                outcome = (
                    "holds",
                    {
                        "claims": [c for p in shown for c in p.claims],
                        "relations": [
                            r.id for r in related if r.subject in {p.id for p in shown} and r.aspect == "data"
                        ],
                    },
                    "O observed it transmitted: " + ", ".join(sorted({f"{p.data} to {p.recipient}" for p in shown})),
                )
        elif comparable and o.get("predicate") == "share":
            recipients = [d.value for d in named if d.type == "declares_recipient" and isinstance(d.value, dict)]
            # the owners when D's documents were collected
            when = at((report.get("collection") or {}).get("started"))
            found = [parties.relate(r["entity"], registry, provider, at=when) for r in recipients if r.get("entity")]
            if recipients and len(found) == len(recipients) and all(f.relation == parties.OWN for f in found):
                outcome = (
                    "fails",
                    {"claims": [d.claim for d in named if d.type == "declares_recipient"]},
                    "the recipient is the provider's own: " + "; ".join(b for f in found for b in f.basis),
                )
        if outcome is None:
            open_.append(
                {
                    "id": f"open:D:{o['id']}",
                    "text": o["text"],
                    "qualifies": o["qualifies"],
                    "kind": "fact",
                    "from": "D",
                    "of": of,
                }
            )
        else:
            result, by, reason = outcome
            decided.append(
                {
                    "id": f"decided:D:{o['id']}",
                    "text": o["text"],
                    "from": "D",
                    "of": of,
                    "outcome": result,
                    "by": by,
                    "reason": reason,
                }
            )
    return open_, decided


def _order(relation_id: str) -> tuple:
    head, _, n = relation_id.rpartition(":")
    return (head, int(n)) if n.isdigit() else (relation_id, 0)


def _entry(ref: dict, related: dict, in_practice: dict, comparable: bool, expected: bool, dimension: str, d=None):
    ids = sorted(set(related.get(_key(ref), [])), key=_order)
    if ids:
        return {"claim": ref, "relations": ids}
    if not comparable:
        return {"claim": ref, "not_related": "not_comparable", "reason": "O's and D's scopes are not comparable"}
    if dimension == "O" and _key(ref) not in in_practice:
        reason = "not a practice: not supported, or a denial"
    elif d is not None and d.type in UNRELATED:
        reason = UNRELATED[d.type]
    elif d is not None and d.type == "declares_purpose":
        reason = (
            "a denial of a purpose: E relates declared purposes only"
            + (
                "; D could not place the purpose, so it denies no purpose in particular"
                if "purpose" in d.unplaced
                else ""
            )
            if d.polarity != "+"
            else "E's expectation stage has no claims"
            if not expected
            else "no relation reads it"
        )
    elif d is not None and d.polarity == "-":
        sale = isinstance(d.value, dict) and d.value.get("sale")
        reason = (
            "a denial of a sale: O observes no consideration" if sale else "a denial no observed practice falls under"
        )
    elif dimension == "O":
        reason = "E's expectation stage has no claims" if not expected else "E formed no expectation of its practice"
    else:
        reason = "no relation reads it"
    return {"claim": ref, "not_related": "not_assessable", "reason": reason}


def open_conditions(
    subjects: Subjects,
    relations: list[Relation],
    statuses: list[Status],
    frame,
    concerns: list,
    tested: list[dict],
    features: list[str],
) -> list[dict]:
    """The conditions E could not decide: a relation's condition, a party, a requirement's undecided condition; and,
    for every experimental claim that a purpose is achieved without a component or with less of it (not dependent,
    or an alternative demonstrated), that it holds for the features the case report covers."""
    out: dict[str, dict] = {}

    def entry(key: str, text: str, kind: str = "fact") -> dict:
        return out.setdefault(
            key, {"id": f"open:{len(out) + 1}", "text": text, "qualifies": [], "kind": kind, "from": "E"}
        )

    for r in relations:
        if r.condition:
            text = r.condition
            if r.condition_kind == "source":  # analysed:<channel>, ... (correspondence.py)
                unread = [c.removeprefix(UNREAD).replace("_", " ") for c in r.condition.split(", ")]
                text = f"whether the {' and the '.join(unread)}, which no stage analysed, declares the practice"
            e = entry(f"condition:{r.condition}", text, r.condition_kind or "fact")
            e["qualifies"].append(r.id)
            r.condition_open = e["id"]
    for p in subjects.practices:
        if (p.party or {}).get("relation") == "?":
            text = f"whether {p.recipient.removeprefix('domain:')} belongs to the provider or another organisation"
            entry(f"party:{p.recipient}", text)["qualifies"] += [r.id for r in relations if r.subject == p.id]
    information = {c.requirement: c.id for c in concerns if c.step == "information_not_given"}
    for s in statuses:
        if s.status != MISSING_IF:
            continue
        for cid in s.conditions:
            if cid.startswith(INCOMPLETE):
                channel = cid.removeprefix(INCOMPLETE).replace("_", " ")
                text = f"whether the part of the {channel} that was not acquired gives the information"
                entry(cid, text, "source")["qualifies"].append(information[s.requirement])
            elif cid.startswith(UNREAD):
                channel = cid.removeprefix(UNREAD).replace("_", " ")
                text = f"whether the {channel}, which could not be analysed, gives the information"
                entry(cid, text, "source")["qualifies"].append(information[s.requirement])
            else:
                entry(f"frame:{cid}", frame.conditions[cid].text)["qualifies"].append(information[s.requirement])
    shown = [
        x["id"]
        for x in tested
        if x["status"] == "supported"
        and ((x["type"] == "dependency" and x.get("relationship") == "not_dependent") or x["type"] == "alternative")
    ]
    if shown:
        text = f"holds for the features the case report covers ({', '.join(features)})"
        entry("features", text)["qualifies"] += shown
    return [{**e, "qualifies": sorted(set(e["qualifies"]))} for e in out.values()]
