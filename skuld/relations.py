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

Not stated: a conflicted justification (E has no claim that challenges a purpose) and a refuted declared necessity
(D states no necessity its rules read).

Pass-through: every claim of O's and D's reports passed on to the Investigator by reference (report digest and claim
id, or JSON pointer for D's claims), with the relations it takes part in or the reason it has none. A claim passed on
is not copied: the Investigator reads it in the report it names, so the claims keep one source.
"""

from ratatoskr import align
from ratatoskr.vocabularies import Vocabulary

from skuld import combine
from skuld.assessment import Subjects
from skuld.correspondence import Relation, covered
from skuld.inputs import ReportRef
from skuld.observe import claims as o_claims
from skuld.transparency import INCOMPLETE, MISSING_IF, UNREAD, Status

VERSION = "2"
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
#: Why a claim of D has no relation, by its type
UNRELATED = {
    "declares_legal_basis": "E forms no expectation of legal bases",
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
) -> list[Relation]:
    """The D–E relations: per positive declared purpose. `vague` names the declarations of a statement concern (ii)
    supports, with the concern."""
    out: list[Relation] = []
    comparable = subjects.comparability.get("comparable") is not False

    def add(**kwargs) -> Relation:
        relation = Relation(id="", type="D-E", tier="rule", **kwargs)
        out.append(relation)
        return relation

    if not hypotheses:
        return out
    for d in subjects.declarations:
        if d.type != "declares_purpose" or d.polarity != "+":
            continue
        if not comparable:
            add(outcome=NOT_COMPARABLE, of=d.claim, subject=d.id, reason="O's and D's scopes are not comparable")
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


def _key(ref: dict) -> tuple:
    return ref["dimension"], ref["report"], ref["claim"]


def passed_on(
    subjects: Subjects,
    observations: list[ReportRef],
    declaration: ReportRef | None,
    relations: list[Relation],
    expected: bool = False,
) -> list[dict]:
    """Every top-level claim of O's reports and every claim of D's report, with its relations or why it has none;
    `expected` says whether E's expectation stage has claims."""
    related: dict[tuple, list[str]] = {}
    in_practice: dict[tuple, str] = {}
    for p in subjects.practices:
        for ref in p.claims:
            in_practice[_key(ref)] = p.id
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
            out.append(_entry(ref, related, in_practice, comparable, expected, "O"))
    for d in subjects.declarations:
        out.append(_entry(d.claim, related, in_practice, comparable, expected, "D", d))
    # D's findings go on to the Investigator by reference (DM9)
    for f in declaration.load().get("findings", []) if declaration else ():
        out.append({"finding": {"report": declaration.sha256, "finding": f["id"]}})
    return out


def from_declaration(declaration: ReportRef | None) -> list[dict]:
    """D's open conditions, which E does not decide, passed on to the Investigator by the condition they continue:
    whether a policy's recipient receives data as a third party, whether its data leaves the device."""
    if declaration is None:
        return []
    return [
        {
            "id": f"open:D:{o['id']}",
            "text": o["text"],
            "qualifies": o["qualifies"],
            "from": "D",
            "of": {"report": declaration.sha256, "open": o["id"]},
        }
        for o in declaration.load().get("open", [])
    ]


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

    def entry(key: str, text: str) -> dict:
        return out.setdefault(key, {"id": f"open:{len(out) + 1}", "text": text, "qualifies": [], "from": "E"})

    for r in relations:
        if r.condition:
            entry(f"condition:{r.condition}", r.condition)["qualifies"].append(r.id)
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
                entry(cid, text)["qualifies"].append(information[s.requirement])
            elif cid.startswith(UNREAD):
                channel = cid.removeprefix(UNREAD).replace("_", " ")
                text = f"whether the {channel}, which could not be analysed, gives the information"
                entry(cid, text)["qualifies"].append(information[s.requirement])
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
