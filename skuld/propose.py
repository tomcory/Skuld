"""
The generator: the named inputs of a workspace, from Loki's exploration of an application and the catalogue.

Every episode of the exploration that Loki's verifier judged carried out is a feature. Its entry point is the state
the exploration reached before the episode; its path, the episode's actions (`path: {run, from, actions}`), so that
one recording serves every feature. The launch is a feature of the catalogue's `launch` family, filled by rule.

Per episode the model is given the flow (the explorer's task, the verifier's reading, the screens from the entry to
the outcome) and the newest version of every family, and answers with a family of the catalogue or a new one, and the
values of its slots, for each feature the flow carries out (at most three). The answer is checked (`problems`); a
refused answer is asked once more with the refusal, and of the second answer only the features that pass are taken,
the others recorded with why. Every prompt and answer is kept:

```text
proposals/e<episode>/a<attempt>/
  record.json    the episode, the generator's version, prompt, model and options, the catalogue's digest
  prompt.txt     the prompt as sent
  answer.json    the model's answer as received
proposals/summary.json   per episode: the case written, or why none was
```

and asked again only when the prompt, the model or its options change (the prompt holds the episode and the families
offered; a new generator version or a change to the catalogue that the prompt does not show asks nothing again). A new family is added to the catalogue; the search space is derived
by rules (`skuld.space`); the inputs are fixed with the generator, the model and the family as their author.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path

import yaml
from ratatoskr.vocabularies import Vocabulary

from skuld import ask, config, inputs, parties, select, space
from skuld import catalogue as cat
from skuld.common import DATA, PURPOSES, vocabulary
from skuld.observe import observe

VERSION = "1"
PROMPT = "propose"
ATTEMPTS = 2
#: Characters of a screen's texts shown to the model
SCREEN_TEXT = 600
#: Screens of a flow shown to the model at most: the first ones and the last ones
MAX_SCREENS = 24
#: The kinds of Loki's episodes that carry out a flow (not a survey of the navigation, not the final logout)
FLOW_KINDS = ("first_run", "flow")

_IDENTIFIERS = re.compile(r"\b(identifiers?|device id|advertising id|android id|gps|coordinates|ip address)\b", re.I)

_STRING = {"type": "string"}
_SLOT_SCHEMA = {
    "type": "object",
    "required": ["name", "kind", "description"],
    "properties": {"name": _STRING, "kind": {"enum": ["text", "screen"]}, "description": _STRING},
}
_ORACLE_SCHEMA = {
    "type": ["object", "null"],
    "required": ["reach", "conditions", "slots"],
    "properties": {
        "reach": {"type": "array", "items": {"type": "integer"}},
        "conditions": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["check", "slot"],
                "properties": {"check": {"enum": ["text_shown", "screen_reached"]}, "slot": _STRING},
            },
        },
        "slots": {"type": "array", "items": _SLOT_SCHEMA},
    },
}
_PURPOSE_SCHEMA = {
    "type": "object",
    "required": [
        "action",
        "object",
        "beneficiary",
        "context",
        "outcome",
        "node",
        "fit",
        "role",
        "requirements",
        "oracle",
    ],
    "properties": {
        **{k: _STRING for k in ("action", "object", "context", "outcome", "node")},
        "beneficiary": {"enum": ["user", "provider"]},
        "fit": {"enum": ["exact", "broader"]},
        "role": {"enum": ["functional", "ancillary"]},
        "requirements": {"type": "array", "items": _STRING},
        "oracle": _ORACLE_SCHEMA,
    },
}
_FEATURE_SCHEMA = {
    "type": "object",
    "required": ["family", "new_family", "slots", "name", "outcome"],
    "properties": {
        "family": _STRING,
        "new_family": {
            "type": ["object", "null"],
            "required": ["id", "name", "entry", "path", "outcome", "purposes"],
            "properties": {
                **{k: _STRING for k in ("id", "name", "entry", "path", "outcome")},
                "purposes": {"type": "array", "items": _PURPOSE_SCHEMA},
            },
        },
        "slots": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "values"],
                "properties": {"name": _STRING, "values": {"type": "array", "items": _STRING}},
            },
        },
        "name": _STRING,
        "outcome": _STRING,
    },
}
ANSWER_SCHEMA = {
    "type": "object",
    "required": ["features"],
    "properties": {"features": {"type": "array", "items": _FEATURE_SCHEMA}},
}
#: The family whose cases are filled by rule, not asked of the model
RULE_FILLED = "launch"
#: Features of one flow at most: a first run, say, whose onboarding ends at the app's main feature
MAX_FEATURES = 3
#: How a new family's condition is written as an oracle template: the slot's kind and the predicate
CHECKS = {
    "text_shown": (
        "text",
        lambda slot: {"any": f"{{{slot}}}", "after_action": "{path_end}", "until_action": "{path_end}"},
    ),
    "screen_reached": (
        "screen",
        lambda slot: {"exact_key": f"{{{slot}}}", "after_action": "{path_start}", "until_action": "{path_end}"},
    ),
}


class ProposalError(Exception):
    """An exploration that cannot be read, or a workspace that exists already."""


@dataclass
class Screen:
    after: int
    episode: str
    screen_id: str
    key: str
    activity: str
    texts: list[str]


@dataclass
class Flow:
    """
    An episode of the exploration that the verifier judged carried out.

    Attributes:
        start: The number of the recording's actions before the episode's first
        end: The number of the recording's actions up to the episode's last
        screens: The app's screens from the entry point (after the `start`th action) to the outcome
    """

    episode: int
    title: str
    where: str
    category: str
    reason: str
    start: int
    end: int
    screens: list[Screen] = field(default_factory=list)

    @property
    def entry(self) -> list[Screen]:
        return [s for s in self.screens if s.after == self.start]

    @property
    def outcome(self) -> list[Screen]:
        return [s for s in self.screens if s.after == self.end]


@dataclass
class Exploration:
    directory: Path
    run_id: str
    package: str
    version: str
    screens: list[Screen]
    flows: list[Flow]

    @property
    def first(self) -> Screen | None:
        return self.screens[0] if self.screens else None


def read(directory: str | Path) -> Exploration:
    """An exploration's flows: the episodes judged carried out, with their actions and screens."""
    directory = Path(directory)
    try:
        meta = json.loads((directory / "run.json").read_text(encoding="utf-8"))
        events = [
            json.loads(line)
            for line in (directory / "events.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        episodes = json.loads((directory / "episodes.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ProposalError(f"{directory}: not an exploration Loki recorded: {e}") from e
    items = {}
    if (directory / "checklist.json").is_file():
        items = {i["id"]: i for i in json.loads((directory / "checklist.json").read_text(encoding="utf-8"))["items"]}
    package = meta.get("package") or meta.get("app", {}).get("package") or ""
    version = str(meta.get("version_name") or meta.get("app", {}).get("version_name") or "?")
    taken, screens, actions_of = 0, [], {}
    for event in events:
        if event.get("type") == "action":
            taken += 1
            actions_of.setdefault(str(event.get("episode")), []).append(taken)
        elif event.get("type") == "screen" and event.get("package") == package:
            screens.append(
                Screen(
                    after=taken + (1 if event.get("label") == "post_action" else 0),
                    episode=str(event.get("episode")),
                    screen_id=event.get("screen_id") or "?",
                    key=event.get("exact_key") or "",
                    activity=event.get("activity") or "",
                    texts=[t for t in event.get("texts") or () if t.strip()],
                )
            )
    ends = {e["episode"]: e for e in events if e.get("type") == "episode_end"}
    flows = []
    for ep in episodes:
        number = ep["episode"]
        item = items.get(ep.get("item_id")) if ep.get("item_id") else None
        if ep.get("kind") not in FLOW_KINDS:
            continue
        done = (item or {}).get("verified") == "yes" or (item is None and (ends.get(number) or {}).get("success"))
        mine = actions_of.get(str(number)) or []
        if not done or not mine:
            continue
        start, end = mine[0] - 1, mine[-1]
        flows.append(
            Flow(
                episode=number,
                title=(item or {}).get("title") or ep.get("label") or "",
                where=(item or {}).get("where") or "",
                category=(item or {}).get("category") or ep.get("kind") or "",
                reason=(item or {}).get("verify_reason") or (ends.get(number) or {}).get("reason") or "",
                start=start,
                end=end,
                screens=[s for s in screens if start <= s.after <= end],
            )
        )
    return Exploration(directory, meta.get("run_id") or directory.name, package, version, screens, flows)


def prompt_template() -> str:
    return (resources.files("skuld") / "prompts" / f"{PROMPT}.md").read_text(encoding="utf-8")


def render_flow(flow: Flow) -> str:
    lines = [
        f"Task given to the explorer: {flow.title}" + (f" (where: {flow.where})" if flow.where else ""),
        f"Verifier's reading: {flow.reason}",
        f"The flow's actions are actions {flow.start + 1} to {flow.end} of the exploration.",
        "",
        "Screens (after = the number of the exploration's actions taken before the screen):",
    ]
    shown = _changes(flow.screens)
    if len(shown) > MAX_SCREENS:
        half = MAX_SCREENS // 2
        shown = [*shown[:half], None, *shown[-half:]]
    for s in shown:
        if s is None:
            lines.append("  …")
            continue
        mark = " FIRST" if s.after == flow.start else " LAST" if s.after == flow.end else ""
        text = " | ".join(s.texts)[:SCREEN_TEXT]
        lines.append(f"- after={s.after}{mark} key={s.key} activity={s.activity.rsplit('.', 1)[-1]}: {text}")
    return "\n".join(lines)


def render_catalogue(families: list[cat.Family]) -> str:
    if not families:
        return "(The catalogue is empty.)"
    return "\n".join(json.dumps(f.summary(), ensure_ascii=False) for f in families)


def problems(
    answer: dict | None, flow: Flow, catalogue: cat.Catalogue, purposes: Vocabulary, titles: list[str] = ()
) -> tuple[list[str], list[dict]]:
    """
    What refuses an answer (no feature, two new families of one id, or what refuses one of its features), and the
    features that pass.
    """
    if answer is None:
        return ["no answer"], []
    features = (answer.get("features") or [])[:MAX_FEATURES]
    if not features:
        return ["no feature"], []
    new = [f["new_family"].get("id") for f in features if f.get("family") == "new" and f.get("new_family")]
    twice = {i for i in new if new.count(i) > 1}
    out = [f"two new families are called {i}" for i in sorted(twice)]
    passing = []
    for n, feature in enumerate(features, 1):
        found = feature_problems(feature, flow, catalogue, purposes, titles)
        out += [f"feature {n}: {p}" for p in found]
        if not found and (feature.get("new_family") or {}).get("id") not in twice:
            passing.append(feature)
    return out, passing


def feature_problems(
    answer: dict, flow: Flow, catalogue: cat.Catalogue, purposes: Vocabulary, titles: list[str] = ()
) -> list[str]:
    """
    What refuses a feature of an answer: an unknown family; a malformed new one, or one whose requirements name a
    datum of the search space (`titles`) or an identifier; or a slot not filled from the flow's screens.
    """
    out = []
    family_id = answer.get("family")
    if family_id == RULE_FILLED:
        return [f"the {RULE_FILLED} is no feature of a flow"]
    if family_id == "new":
        new = answer.get("new_family")
        if not new:
            return ["family is 'new' but new_family is empty"]
        if catalogue.get(new.get("id", "")) is not None:
            out.append(f"the family {new.get('id')} exists: choose it, or give the new family another id")
        try:
            data = new_family(new, flow, "", "", {})
            cat.check(data)
        except (cat.CatalogueError, KeyError, ValueError) as e:
            return [*out, f"the new family is malformed: {e}"]
        for p in data["purposes"]:
            if p["node"] not in purposes:
                out.append(f"purpose {p['id']}: {p['node']!r} is no node of the purpose vocabulary")
            for r in p["requirements"]:
                if hit := names_datum(r["statement"], titles):
                    out.append(f"requirement {r['statement']!r} names {hit!r}, data whose need the experiment tests")
        slots = _slots(data)
    else:
        family = catalogue.get(family_id or "")
        if family is None:
            return [f"{family_id!r} is no family of the catalogue"]
        slots = _slots(family.data)
    values = {s["name"]: s["values"] for s in answer.get("slots") or ()}
    for name, slot in slots.items():
        given = [v for v in values.get(name) or () if v.strip()]
        if not given:
            out.append(f"slot {name} is not filled")
            continue
        out += [f"slot {name}: {p}" for p in _slot_problems(slot["kind"], given, flow)]
    return out


def _slot_problems(kind: str, values: list[str], flow: Flow) -> list[str]:
    """A slot's values must come from the flow's screens and tell its outcome from its entry point."""
    out = []
    if kind == "text":
        for v in values:
            if not any(v in t for s in flow.outcome for t in s.texts):
                out.append(f"{v!r} is not shown by the screens after the flow's last action")
            elif any(v in t for s in flow.entry for t in s.texts):
                out.append(
                    f"{v!r} is shown by the flow's first screen too, so it does not tell that the feature worked"
                )
    elif kind == "screen":
        if len(values) != 1:
            out.append("a screen slot takes one key")
        keys = {s.key for s in flow.screens if s.after > flow.start}
        entry = {s.key for s in flow.entry}
        for v in values:
            if v not in keys:
                out.append(f"{v!r} is not the key of a screen of the flow after its start")
            elif v in entry:
                out.append(f"{v!r} is the flow's first screen")
    elif kind == "activity":
        if len(values) != 1:
            out.append("an activity slot takes one activity")
        for v in values:  # each, since the first is the one bound
            if not any(s.activity.endswith(v) for s in flow.screens):
                out.append(f"{v!r} is not the activity of a screen of the flow")
    return out


def names_datum(statement: str, titles) -> str | None:
    """The datum or identifier a requirement names, if it names one."""
    for title in titles:
        if re.search(rf"\b{re.escape(title)}\b", statement, re.I):
            return title
    m = _IDENTIFIERS.search(statement)
    return m.group(0) if m else None


def new_family(new: dict, flow: Flow, application: str, run: str, author: dict) -> dict:
    """A catalogue family from the model's description of a new one."""
    purposes = []
    for n, p in enumerate(new["purposes"], 1):
        requirements = [{"id": f"R{m}", "statement": s.strip()} for m, s in enumerate(p["requirements"], 1)]
        oracle = None
        if p.get("oracle"):
            o = p["oracle"]
            declared = {s["name"]: {"kind": s["kind"], "description": s["description"]} for s in o.get("slots") or ()}
            success = []
            for c in o["conditions"]:
                kind, args = CHECKS[c["check"]]
                if declared.get(c["slot"], {}).get("kind") != kind:
                    raise ValueError(f"check {c['check']} needs a slot of kind {kind}: {c['slot']}")
                success.append({c["check"]: args(c["slot"])})
            reach = [f"R{i}" for i in o["reach"] if 1 <= i <= len(requirements)]
            if len(reach) != len(o["reach"]):
                raise ValueError(f"reach {o['reach']} names requirements the purpose does not have")
            oracle = {
                "reach": reach,
                "success": success,
                "invalid": [dict(i) for i in cat.INVALID],
                "measurements": [],
                "slots": declared,
            }
        purposes.append(
            {
                "id": f"P{n}",
                **{k: p[k].strip() for k in ("action", "object", "beneficiary", "context", "outcome", "node")},
                "fit": p["fit"],
                "specificity": "sufficient",
                "role": p["role"],
                "requirements": requirements,
                "oracle": oracle,
            }
        )
    return {
        "id": new["id"].strip(),
        "version": 1,
        "name": new["name"].strip(),
        "entry": new["entry"].strip(),
        "path": new["path"].strip(),
        "outcome": new["outcome"].strip(),
        "purposes": purposes,
        "author": author,
        "created": datetime.now(UTC).date().isoformat(),
        "derived_from": {"application": application, "run": run, "episode": flow.episode},
        "reviewed": None,
    }


def _slots(data: dict) -> dict:
    return {n: s for p in data["purposes"] if p.get("oracle") for n, s in (p["oracle"].get("slots") or {}).items()}


def _changes(screens: list[Screen]) -> list[Screen]:
    """The screens, each listed again only when its text changed."""
    out = []
    for s in screens:
        if not out or (out[-1].key, out[-1].texts, out[-1].after) != (s.key, s.texts, s.after):
            out.append(s)
    return out


# -- the workspace ------------------------------------------------------------------------------------------------


def propose(
    exploration: str | Path,
    root: str | Path,
    catalogue_root: str | Path,
    model: str,
    verdandi: list[str],
    api: str = "ollama",
    offline: bool = False,
    provider=None,
    selection: dict | None = None,
    registry: str | Path | None = None,
) -> dict:
    """
    Writes and fixes the workspace's inputs; returns the summary (per episode: the case, or why there is none).
    With a selection (`skuld select`), only the episodes of the practices it chose, and in each case only the
    components that vary a chosen practice's, so that no run is made that the assessment did not ask for.

    Raises ProposalError if the workspace already has fixed inputs: generated inputs are fixed once, before the runs.
    """
    root = Path(root)
    if (root / inputs.FROZEN).is_file():
        raise ProposalError(f"{root} has fixed inputs already")
    exp = read(exploration)
    catalogue = cat.load(catalogue_root)
    purposes = vocabulary(PURPOSES)
    data = vocabulary(DATA)
    application = f"{exp.package}@{exp.version}"
    (root / "cases").mkdir(parents=True, exist_ok=True)
    (root / "oracles").mkdir(exist_ok=True)
    settings = {
        "application": {"package": exp.package, "version": exp.version},
        "runs": inputs.portable(exp.directory.parent, root),
        "verdandi": verdandi,
        "recording": exp.run_id,
    }
    (root / "workspace.yaml").write_text(yaml.safe_dump(settings, sort_keys=False), encoding="utf-8", newline="\n")
    report = observe(root, exp.run_id, exp.directory, verdandi)
    template = prompt_template()
    generator = {"id": "skuld.propose", "version": VERSION, "prompt_sha256": _sha(template)}
    summary: dict = {"generator": generator, "recording": exp.run_id, "catalogue": catalogue.sha256, "episodes": {}}
    authors: dict[str, dict] = {}
    wanted, keep = (None, None) if selection is None else select.keeps(selection, data)
    own = space.provider_own(parties.load_registry(registry), parties.controller(None, exp.package))
    if selection is not None:
        summary["selection"] = {"created": selection["created"], "chosen": [e["id"] for e in select.chosen(selection)]}

    launch = catalogue.get(RULE_FILLED)
    if launch is not None and exp.first is not None and (wanted is None or wanted & {"?", "0"}):
        bindings = {"first_activity": exp.first.activity, "path_start": 0, "path_end": 0}
        feature = {
            "id": "F-launch",
            "name": "launch",
            "entry": launch.data["entry"],
            "path": None,
            "outcome": launch.data["outcome"],
        }
        author = _author(generator, None, launch)
        written = _write_case(
            root, "launch", feature, launch, bindings, report, {"?", "0"}, exp.package, data, authors, author, keep, own
        )
        if written is not None:
            summary["episodes"]["launch"] = {"cases": [{"case": "launch", "family": launch.key}], "title": "launch"}

    sampling = config.options("propose")
    for flow in exp.flows:
        key = f"e{flow.episode}"
        if wanted is not None and (
            str(flow.episode) not in wanted or not space.derive(report, {str(flow.episode)}, exp.package, keep, own)[0]
        ):
            summary["episodes"][key] = {"cases": [], "title": flow.title, "refused": ["no practice of it was chosen"]}
            continue
        prompt = template.format(
            catalogue=render_catalogue([f for f in catalogue.latest() if f.id != RULE_FILLED]),
            nodes=", ".join(n.id for n in purposes),
            flow=render_flow(flow),
        )
        titles = _titles(space.derive(report, {str(flow.episode)}, exp.package, own=own)[0], data)
        passing: list[dict] = []

        def refuse(text: str | None, flow=flow, titles=titles) -> list[str]:
            nonlocal passing
            found, passing = problems(_parse(text) if text else None, flow, catalogue, purposes, titles)
            return found

        sample, refused, _ = ask.ask_with_feedback(
            lambda attempt, key=key: root / "proposals" / key / f"a{attempt}",
            prompt,
            ANSWER_SCHEMA,
            lambda asked, flow=flow: {
                "episode": flow.episode,
                "generator": {"id": "skuld.propose", "version": VERSION},
                "prompt": {"id": PROMPT, "sha256": ask.sha256(asked)},
                "catalogue": catalogue.sha256,
            },
            ("prompt",),
            refuse,
            attempts=ATTEMPTS,
            seed=sampling.seed,
            model=model,
            api=api,
            options=sampling,
            offline=offline,
            provider=provider,
        )
        if sample is not None and sample.text is None:
            refused, passing = problems(None, flow, catalogue, purposes, titles)
        folder = sample.folder if sample is not None else None
        summary["episodes"][key] = {"cases": [], "title": flow.title}
        if refused:
            summary["episodes"][key]["refused"] = refused
        for n, chosen in enumerate(passing):
            case_id = key if n == 0 else f"{key}{chr(ord('a') + n)}"
            entry = _feature_case(
                root,
                case_id,
                chosen,
                flow,
                exp,
                catalogue,
                application,
                model,
                api,
                folder,
                generator,
                report,
                data,
                authors,
                contains_launch="launch" in summary["episodes"],
                keep=keep,
                own=own,
            )
            if entry is None:
                summary["episodes"][key].setdefault("refused", []).append(
                    f"case {case_id}: no component of it varies a chosen practice's"
                )
                continue
            summary["episodes"][key]["cases"].append(entry)

    from skuld.execute import ExecutionError, interventions

    try:
        interventions(inputs.load(root))
    except (ExecutionError, inputs.InputError) as e:
        raise ProposalError(f"the generated cases cannot be run together: {e}") from e
    fixed = inputs.freeze(root, {"kind": "model", "name": model, "prompt": f"skuld.propose {VERSION}"}, authors=authors)
    summary["fixed"] = fixed
    (root / "proposals").mkdir(exist_ok=True)
    (root / "proposals" / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    return summary


def _feature_case(
    root,
    case_id,
    answer,
    flow,
    exp,
    catalogue,
    application,
    model,
    api,
    folder,
    generator,
    report,
    data,
    authors,
    contains_launch,
    keep=None,
    own=None,
) -> dict | None:
    """Writes the case of one feature of an answer, with a new family added to the catalogue where it gives one; None
    where a selection keeps no component of it."""
    if answer["family"] == "new":
        prompt_record = json.loads((folder / "record.json").read_text(encoding="utf-8"))
        family = catalogue.add(
            new_family(
                answer["new_family"],
                flow,
                application,
                exp.run_id,
                {
                    "kind": "model",
                    "name": model,
                    "prompt": f"skuld.propose {VERSION}",
                    # a new family's author: the digest of the prompt as asked, for this episode (a case's
                    # author, _author, names the template's instead)
                    "sha256": prompt_record["prompt"]["sha256"],
                },
            )
        )
    else:
        family = catalogue.get(answer["family"])
    values = {s["name"]: [v for v in s["values"] if v.strip()] for s in answer["slots"]}
    bindings = {"path_start": flow.start, "path_end": flow.end}
    for name, slot in _slots(family.data).items():
        bindings[name] = values[name][0] if slot["kind"] != "text" else values[name]
    feature = {
        "id": f"F-{case_id}",
        "name": answer["name"].strip() or family.data["name"],
        "entry": f"the state the exploration {exp.run_id} reached after its first {flow.start} actions "
        f"({family.data['entry']})",
        "path": {"run": exp.run_id, "from": flow.start, "actions": flow.end},
        "outcome": answer["outcome"].strip() or family.data["outcome"],
    }
    if flow.start == 0 and contains_launch:
        feature["contains"] = ["F-launch"]
    author = _author(generator, {"api": api, "name": model}, family, folder.relative_to(root).as_posix())
    named = _write_case(
        root,
        case_id,
        feature,
        family,
        bindings,
        report,
        {str(flow.episode)},
        exp.package,
        data,
        authors,
        author,
        keep,
        own,
    )
    if named is None:
        return None
    entry = {"case": case_id, "family": family.key}
    if named:
        entry["requirements"] = named
    return entry


def _write_case(
    root, case_id, feature, family, bindings, report, episodes, package, data, authors, author, keep=None, own=None
) -> list[str] | None:
    """Writes a case and its oracles; returns the requirements that name a datum of its search space (kept, reported),
    or None, writing nothing, where `keep` keeps no component of it."""
    components, alternatives = space.derive(report, episodes, package, keep, own)
    if keep is not None and not components:
        return None
    titles = _titles(components, data)
    purposes, named = [], []
    for n, p in enumerate(family.data["purposes"], 1):
        pid = f"P-{case_id}-{n}"
        rid = {r["id"]: f"R-{case_id}-{n}.{m}" for m, r in enumerate(p["requirements"], 1)}
        for r in p["requirements"]:
            if hit := names_datum(r["statement"], titles):
                named.append(f"{rid[r['id']]} names {hit!r}")
        oracle_key = None
        if p.get("oracle"):
            o = p["oracle"]
            oracle_id = f"O-{case_id}-{n}"
            oracle = {
                "id": oracle_id,
                "version": 1,
                "purpose": pid,
                "reach": [rid[r] for r in o["reach"]],
                "success": cat.fill(o["success"], bindings),
                "invalid": cat.fill(o.get("invalid") or [], bindings),
                "measurements": cat.fill(o.get("measurements") or [], bindings),
            }
            path = root / "oracles" / f"{oracle_id}@1.yaml"
            path.write_text(yaml.safe_dump(oracle, sort_keys=False, allow_unicode=True), encoding="utf-8", newline="\n")
            authors[f"oracles/{path.name}"] = author
            oracle_key = f"{oracle_id}@1"
        purposes.append(
            {
                "id": pid,
                **{k: p[k] for k in ("action", "object", "beneficiary", "context", "outcome", "node", "fit")},
                "provenance": "feature",
                "specificity": p["specificity"],
                "role": p["role"],
                "requirements": [{"id": rid[r["id"]], "statement": r["statement"]} for r in p["requirements"]],
                "oracle": oracle_key,
            }
        )
    case = {
        "id": case_id,
        "family": {"id": family.id, "version": family.version, "sha256": family.sha256},
        "feature": feature,
        "purposes": purposes,
        "components": components,
        "search_space": {"alternatives": alternatives},
    }
    path = root / "cases" / f"{case_id}.yaml"
    path.write_text(
        yaml.safe_dump(case, sort_keys=False, allow_unicode=True, width=120), encoding="utf-8", newline="\n"
    )
    authors[f"cases/{path.name}"] = author
    return named


def _titles(components: list[dict], data: Vocabulary) -> list[str]:
    """The names of the data a case's search space varies: its nodes' titles and those above them, but the top ones."""
    titles = []
    for c in components:
        node = c.get("node")
        if not node or node not in data:
            continue
        for n in (node, *data.ancestors(node)):
            if data[n].parents:
                titles.append(data[n].title)
    return sorted(set(titles), key=len, reverse=True)


def _author(generator: dict, model: dict | None, family: cat.Family, answer: str | None = None) -> dict:
    """
    The author of a generated input: the generator's model, or for a case filled by rule alone, the family's author;
    with the generator and the family.
    """
    if model:
        author = {"kind": "model", "name": model["name"], "prompt": f"skuld.propose {VERSION}"}
        author["sha256"] = generator["prompt_sha256"]  # the template's digest, alike for every case it made
    else:
        author = {k: v for k, v in (family.data.get("author") or {"kind": "person", "name": "?"}).items()}
    author |= {
        "generated": {
            "generator": generator,
            "family": {
                "id": family.id,
                "version": family.version,
                "sha256": family.sha256,
                "reviewed": family.reviewed,
            },
        },
    }
    if answer:
        author["generated"]["answer"] = answer
    return author


def _parse(text: str) -> dict | None:
    try:
        answer = json.loads(text)
    except ValueError:
        return None
    return answer if isinstance(answer, dict) else None


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
