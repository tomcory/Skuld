"""
Placement (QUALIFICATION_PLAN.md §2.1): the assessment divided into cases and sections, by the structure of the claims,
never by their text.

    practice case          one per practice: its relations; the declarations of practice its O–D relations relate;
                           the justifications nested under those (a purpose or legal basis under the declaration it
                           belongs to: `policy:/dataDisclosed/0/purposes/0` under `policy:/dataDisclosed/0`); the D–E
                           relations and concerns of all of these; its own concerns and E's claims about it; the gaps
                           and open conditions of any of them
    declaration-only case  one per declaration of practice no practice case holds, with its justifications
    declared purposes      one row per statement of purpose (the declarations said in the same words, 8.8) and per
                           purpose said in no words of the provider, whether a case holds them too or not; and one per
                           other justification (a legal basis) no case holds
    collection             the collection's requirements, with the concerns whose subject is the collection
    unplaced               whatever none of these holds, with the reason

A declaration held by two practice cases is held by both. A concern on a statement of purpose names the statement's
first declaration; the D–E relation of every other declaration of the statement names the concern, so that each
declaration's case holds it.

A case holds its declared purposes and their concerns as references; the requirements whose subject is a declaration
(purpose specificity) are decided in the purposes' rows, never in the case (8.8).
"""

from dataclasses import dataclass, field

VERSION = "3"  # 3: legal bases are no declared-purpose rows
COMPONENT = {"role": "method", "id": "skuld.qualify.placement", "version": VERSION}


@dataclass
class Holding:
    """What a case or a section row holds, by id."""

    id: str
    kind: str  # practice, declaration, declared_purpose, collection
    subject: str
    declarations: list[str] = field(default_factory=list)  # D-n held
    relations: list[str] = field(default_factory=list)
    concerns: list[str] = field(default_factory=list)
    claims: list[str] = field(default_factory=list)  # E's claims
    gaps: list[str] = field(default_factory=list)
    open: list[str] = field(default_factory=list)

    def ids(self) -> set[str]:
        return {self.subject, *self.declarations, *self.relations, *self.concerns, *self.claims}


def _add(items: list[str], *new: str) -> None:
    for x in new:
        if x not in items:
            items.append(x)


class Index:
    """The assessment's items by id, and the structure placement reads."""

    def __init__(self, report: dict, requirements: dict[str, str] | None = None):
        self.report = report
        self.requirements = requirements or {}  # the frame's requirements by id, with the kind of their subject
        self.practices = {p["id"]: p for p in report["subjects"]["practices"]}
        self.declarations = {d["id"]: d for d in report["subjects"]["declarations"]}
        self.by_claim = {d["claim"]["claim"]: d["id"] for d in report["subjects"]["declarations"]}
        self.relations = {r["id"]: r for r in report["relations"]}
        self.concerns = {c["id"]: c for c in report["concerns"]}
        self.claims = {c["id"]: c for c in report["claims"]}
        self.gaps = {g["id"]: g for g in report["gaps"]}
        self.open = {o["id"]: o for o in report["open"]}
        practice_claims = {
            d["claim"]["claim"]: d["id"] for d in report["subjects"]["declarations"] if d.get("kind") == "practice"
        }
        #: a justification's parent: the declaration of practice its claim id is nested under
        self.parent: dict[str, str | None] = {}
        for d in report["subjects"]["declarations"]:
            if d.get("kind") != "justification":
                continue
            cid = d["claim"]["claim"]
            parent = None
            while "/" in cid.split(":", 1)[-1]:
                cid = cid.rsplit("/", 1)[0]
                if cid in practice_claims:
                    parent = practice_claims[cid]
                    break
            self.parent[d["id"]] = parent
        self.children: dict[str, list[str]] = {}
        for j, p in self.parent.items():
            if p:
                self.children.setdefault(p, []).append(j)
        self.relations_of: dict[str, list[str]] = {}
        for r in report["relations"]:
            if r.get("subject"):
                self.relations_of.setdefault(r["subject"], []).append(r["id"])
        self.concerns_of: dict[str, list[str]] = {}
        for c in report["concerns"]:
            self.concerns_of.setdefault(c["subject"], []).append(c["id"])
        self.claims_of: dict[str, list[str]] = {}
        for c in report["claims"]:
            self.claims_of.setdefault(c["subject"], []).append(c["id"])

    def declaration_of(self, ref: dict) -> str | None:
        return self.by_claim.get(ref["claim"]) if ref.get("dimension") == "D" else None


def _fill(index: Index, h: Holding, declarations: list[str]) -> None:
    """A holding's declarations with their justifications, and the relations, concerns and claims of all of them."""
    for d in declarations:
        _add(h.declarations, d, *index.children.get(d, []))
    for d in list(h.declarations):
        _add(h.relations, *index.relations_of.get(d, []))
        _add(h.concerns, *index.concerns_of.get(d, []))
    for rid in list(h.relations):
        r = index.relations[rid]
        if r["type"] == "D-E":
            # a concern on a statement names its first declaration; the others' D–E relations name it
            _add(h.concerns, *(t["claim"] for t in r.get("to", []) if t["claim"] in index.concerns))
    _add(h.claims, *index.claims_of.get(h.subject, []))


def place(index: Index) -> tuple[list[Holding], list[Holding], list[Holding]]:
    """The practice and declaration-only cases and the declared-purposes and collection rows, without their gaps and
    open conditions (attach)."""
    cases: list[Holding] = []
    held: set[str] = set()
    for pid in sorted(index.practices):
        h = Holding(f"case:{pid}", "practice", pid)
        h.relations = list(index.relations_of.get(pid, []))
        h.concerns = list(index.concerns_of.get(pid, []))
        related = []
        for rid in h.relations:
            r = index.relations[rid]
            if r["type"] == "O-D":
                related += [d for t in r.get("to", []) if (d := index.declaration_of(t))]
        _fill(index, h, sorted(set(related), key=_order))
        held |= set(h.declarations)
        cases.append(h)
    for did in sorted(index.declarations, key=_order):
        d = index.declarations[did]
        if d.get("kind") != "practice" or did in held:
            continue
        h = Holding(f"case:{did}", "declaration", did)
        _fill(index, h, [did])
        held |= set(h.declarations)
        cases.append(h)
    purposes: list[Holding] = []
    # a declared purpose's row holds purposes only: a legal basis is information the collection's rows assess
    # (Art. 13(1)(c)), not a purpose the reasoning tier judges (POST_PAPER_FIXES 3: 209 per family filed as purposes)
    justifications = [
        d
        for d in sorted(index.declarations, key=_order)
        if index.declarations[d].get("kind") == "justification"
        and index.declarations[d].get("type") == "declares_purpose"
    ]
    statements: dict[str, list[str]] = {}
    for did in justifications:
        if index.declarations[did].get("statement"):
            statements.setdefault(index.declarations[did]["statement"], []).append(did)
    rows = {ds[0]: ds for ds in statements.values()}
    for d in justifications:
        # a purpose said in no words of the provider (a category of a form) is a row of its own
        if not index.declarations[d].get("statement"):
            rows[d] = [d]
    for first in sorted(rows, key=_order):
        h = Holding(f"row:{first}", "declared_purpose", first)
        _fill(index, h, rows[first])
        purposes.append(h)
    collection: list[Holding] = []
    transparency = (index.report["subjects"].get("collection") or {}).get("transparency", [])
    for s in transparency:
        h = Holding(f"row:collection:{s['requirement']}", "collection", "collection")
        h.concerns = [
            c["id"]
            for c in index.report["concerns"]
            if c["subject"] == "collection" and c["requirement"] == s["requirement"]
        ]
        collection.append(h)
    return cases, purposes, collection


def _order(did: str) -> tuple:
    head, _, n = did.rpartition("-")
    return (head, int(n)) if n.isdigit() else (did, 0)


def attach(index: Index, holdings: list[Holding], unassessed: dict[str, set[str]]) -> None:
    """Each gap and open condition into every holding that holds what it concerns: a gap of a requirement (a question
    of the reasoning tier not asked) into those that apply the requirement and were not assessed for it
    (`unassessed`, by holding id), a gap of the collection into the collection's rows."""
    collection = [h for h in holdings if h.kind == "collection"]
    requirements = {r for rs in unassessed.values() for r in rs} | set(index.requirements)
    holders: dict[str, list[Holding]] = {}
    for h in holdings:
        for x in h.ids():
            holders.setdefault(x, []).append(h)
    # claims of an experimental case: a gap of the case concerns the practices whose claims it tested
    by_case: dict[str, set[str]] = {}
    for c in index.report["claims"]:
        if c.get("case"):
            by_case.setdefault(c["case"], set()).add(c["subject"])
    for g in index.report["gaps"]:
        targets: list[Holding] = []
        of = g.get("of")
        subject = g["id"].split(":", 1)[1].rsplit(":", 1)[0]
        if of == "collection":
            targets = collection or []
        elif of in requirements:
            targets = [h for h in holdings if of in unassessed.get(h.id, ())]
        elif of:
            targets = holders.get(of, [])
        elif subject in by_case:
            targets = [h for p in sorted(by_case[subject]) for h in holders.get(p, [])]
        for h in targets:
            _add(h.gaps, g["id"])
    for o in index.report["open"]:
        targets = []
        for q in o["qualifies"]:
            targets += holders.get(q, [])
            if q in index.by_claim:  # D's open conditions qualify D's claims by their ids
                targets += holders.get(index.by_claim[q], [])
        for h in targets:
            _add(h.open, o["id"])


def unplaced(index: Index, holdings: list[Holding]) -> list[dict]:
    """Every relation, concern, gap and open condition no holding holds, with the reason."""
    placed = {
        "relations": {x for h in holdings for x in h.relations},
        "concerns": {x for h in holdings for x in h.concerns},
        "gaps": {x for h in holdings for x in h.gaps},
        "open": {x for h in holdings for x in h.open},
    }
    out = []
    for kind, items in (
        ("relations", index.relations),
        ("concerns", index.concerns),
        ("gaps", index.gaps),
        ("open", index.open),
    ):
        for i in items:
            if i not in placed[kind]:
                out.append({"id": i, "reason": _why(index, kind, items[i])})
    return out


def _why(index: Index, kind: str, item: dict) -> str:
    if kind == "gaps" and item.get("of"):
        return f"it concerns {item['of']}, which no case or section holds"
    if kind == "open":
        return f"it qualifies {', '.join(item['qualifies'])}, none of which a case or section holds"
    subject = item.get("subject")
    if (index.declarations.get(subject) or {}).get("type") == "declares_legal_basis":
        return (
            f"its subject {subject} is a declared legal basis, which the collection's rows assess as information "
            "given, not a declared purpose"
        )
    return f"its subject {subject} is in no case or section" if subject else "it names no subject"
