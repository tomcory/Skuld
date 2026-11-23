"""
The verification of an intervention, on the run it changes.

An intervention is verified if the run's records establish (i) its effect, for each changed
component (no read of a hooked source handed the application another value than the imposed one,
which holds also if the application did not read the source; no transmission of any data to a
removed recipient, every connection to its hosts dropped). It failed if (i) fails. For each changed
datum, (ii) the substitution check asks whether the application read another platform source of data
of its kind more often than in the baseline runs: a source it did is a substitute, the identifier the
application fell back to, which is an outcome of the run of its own (`Verification.substitutes`), not a
failure of the intervention (20 Nov 2026; before, a substitute failed the run, so that two of Remini's
three runs were refused when the application fell back to the App Set ID). What no instrument of the
run covers is an unverifiable part, which does not fail the run but is reported with it: an identifier
source not hooked, or connections the capture recorded without a host. A run's effect may hold because the
application never read the source; it then decides nothing unless the experimental case's baseline runs show the
component (read its source, or transmit to its recipient): otherwise the analysis compares nothing
for it (`experiments`, C2).

Loki records whether every hooked source returned what its setting says; Heimdall records the
connections it dropped; O's report gives the values read and the transmissions. Verification reads
all three.
"""

from dataclasses import dataclass, field

from skuld.common import under
from skuld.inputs import Alternative, Case
from skuld.observe import source_reads, transmissions_to
from skuld.runs import Run

#: The data nodes of the sources Loki's agent hooks
SOURCE_NODES = {
    "advertising_id": "device-or-other-ids.advertising-id",
    "android_id": "device-or-other-ids.android-id",
    "app_set_id": "device-or-other-ids.app-set-id",
    "drm_id": "device-or-other-ids.drm-id",
    "gsf_id": "device-or-other-ids.gsf-id",
    "location": "location.coordinates",
    "sim_id": "device-or-other-ids.sim-ids",
}

_IDENTIFIERS = (
    "device-or-other-ids.advertising-id",
    "device-or-other-ids.android-id",
    "device-or-other-ids.app-set-id",
    "device-or-other-ids.drm-id",
    "device-or-other-ids.gsf-id",
    "device-or-other-ids.hardware-ids",
    "device-or-other-ids.sim-ids",
)

#: For a datum, the platform sources of data of its kind, which could stand in for it once it is removed. Location
#: has none the application reads on the device: locating its network address happens at the recipient
SUBSTITUTES = {node: tuple(n for n in _IDENTIFIERS if n != node) for node in _IDENTIFIERS}

#: Sources the platform closes to applications from an SDK level on (without privileged permissions)
CLOSED_FROM = {"device-or-other-ids.hardware-ids": 29, "device-or-other-ids.sim-ids": 29}

NODE_SOURCES = {node: source for source, node in SOURCE_NODES.items()}

#: The verification as a named method of the case report: 2 since a substitute is an outcome of the run
#: (`Verification.substitutes`) and no longer fails its verification (20 Nov 2026); 1 was recorded as Skuld's version
VERSION = "2"


@dataclass
class Verification:
    """
    Attributes:
        status: 'verified', 'failed', or 'not_applicable' for a baseline run
        effect, substitution: Checks, each {component or node, holds, note}; a substitution check that does not
            hold names a substitute (`substitute: true`)
        substitutes: The data nodes of the substitutes, the identifiers the application fell back to: read more
            often than in the baseline runs once the changed datum was replaced or removed
        unverifiable: Unv, the parts no instrument of the run covers
        items: What the checks rest on: O's items and claims of the run, and Loki's and Heimdall's records,
            each with its kinds and a pointer
    """

    status: str
    effect: list[dict] = field(default_factory=list)
    substitution: list[dict] = field(default_factory=list)
    substitutes: list[str] = field(default_factory=list)
    unverifiable: list[str] = field(default_factory=list)
    items: list[dict] = field(default_factory=list)

    def cite(self, key: str, kinds: list[str], source: str, record: str, locator: str = "") -> str:
        """Records an item of O or of an instrument's record that a check rests on; returns its key."""
        if not any(i["key"] == key for i in self.items):
            pointer = {"source": source, "record": record, **({"locator": locator} if locator else {})}
            self.items.append({"key": key, "kinds": kinds, "pointer": pointer})
        return key


def instruments(report: dict) -> dict:
    """The instruments' records of O's scope: Loki's (`frida`) and each capture's (`heimdall:<capture>`)."""
    out = {}
    for scope in report.get("scopes") or ():
        out.update(((scope.get("context") or {}).get("instruments")) or {})
    return out


def _frida(report: dict) -> dict:
    record = instruments(report).get("frida")
    return record if isinstance(record, dict) else {}


def _captures(report: dict) -> list[dict]:
    return [r for name, r in instruments(report).items() if name.startswith("heimdall:") and isinstance(r, dict)]


def settings(report: dict) -> dict[str, str]:
    """The run's instrumentation settings by source, e.g. {'advertising_id': 'replace:0000…'}, as O's scope gives them."""
    out = {}
    for setting in _frida(report).get("settings") or ():
        source, _, value = setting.partition("=")
        out[source] = value
    return out


def blocked_hosts(report: dict) -> list[str]:
    """The hosts the capture blocked, as its settings in O's scope give them."""
    return sorted({h for c in _captures(report) for h in (c.get("settings") or {}).get("blocked_hosts") or ()})


def hook_status(report: dict, source: str) -> str | None:
    """Loki's status of a hooked source: 'verified', 'not_exercised' (never read), 'unavailable' or 'violated'."""
    hooks = _frida(report).get("hooks")
    return ((hooks if isinstance(hooks, dict) else {}).get(source) or {}).get("status")


def instrumented(report: dict) -> str | None:
    """
    What is wrong with the instrumentation of a run as a whole: a failed check of Loki's session, or a hook whose
    calls were not as set. A hook never called is no fault: the application did not read the source.
    """
    frida = _frida(report)
    if not frida:
        return None
    if frida.get("error"):
        return f"the instrumentation failed: {frida['error']}"
    if frida.get("checks_failed"):
        return f"Loki's checks failed: {', '.join(frida['checks_failed'])}"
    violated = [s for s in settings(report) if hook_status(report, s) == "violated"]
    return f"calls not as set: {', '.join(violated)}" if violated else None


def baseline_problem(report: dict) -> str | None:
    """Why a run cannot serve as a baseline run: a source changed, a host blocked, or the instrumentation at fault."""
    # 'record' hands the value on unchanged and records it (the base configuration's sinks, storage and crypto, are
    # recorded in every condition, execute.configuration): no change of the source
    # the device's setup (inputs.SETUP: Loki's telephony hook, the study's SIM) is the same in every run and no change
    # (23 Nov 2026: the re-run's experiments had no baseline run at all, as Skuld 0.12.2 left it out of describe only)
    from skuld.inputs import SETUP

    changed = [f"{s}={v}" for s, v in settings(report).items() if v not in ("pass", "record") and s not in SETUP]
    if changed:
        return f"sources changed: {', '.join(changed)}"
    if blocked_hosts(report):
        return f"hosts blocked: {', '.join(blocked_hosts(report))}"
    return instrumented(report)


def verify(
    run: Run, report: dict, alternative: Alternative, case: Case, baseline_reads: dict[str, list[int]]
) -> Verification:
    """
    The verification of a run under an alternative.

    Args:
        report: O's report of the run
        baseline_reads: Per hooked source, the number of reads of it in each baseline run of the experimental case
    """
    v = Verification(status="verified")
    hooked = settings(report)
    fault = instrumented(report)
    if fault:
        v.effect.append({"component": "instrumentation", "holds": False, "note": fault})
    wanted = alternative.intervention.get("sources") or {}
    blocks = alternative.intervention.get("block_hosts") or []

    for source, setting in wanted.items():
        if hooked.get(source) != setting:
            v.effect.append(
                {
                    "component": source,
                    "holds": False,
                    "note": f"the run's setting is {hooked.get(source)!r}, not {setting!r}",
                }
            )
    for host in blocks:
        if not any(under(host, b) for b in blocked_hosts(report)):
            v.effect.append({"component": host, "holds": False, "note": "the run did not block the host"})

    for change in alternative.changes:
        component = case.component(change["component"])
        if component.dimension == "R":
            v.effect.append(_recipient_removed(v, report, component.entity, blocks))
            continue
        source = NODE_SOURCES[component.node]
        v.effect.append(_source_imposed(v, report, component.id, source, wanted[source]))
        _substitution(v, run, report, component.node, hooked, baseline_reads)

    # a substitute is the run's outcome, not a fault of its intervention: it does not fail the verification
    v.substitutes = sorted({c["node"] for c in v.substitution if c["holds"] is False})
    if any(c["holds"] is not True for c in v.effect):
        v.status = "failed"
    return v


def imposes(alternative: Alternative, case: Case) -> list[str]:
    """The changed components the alternative's intervention does not impose: none, for an alternative a run can test."""
    wanted = alternative.intervention.get("sources") or {}
    missing = []
    for change in alternative.changes:
        component = case.component(change["component"])
        if component.dimension == "R":
            if not alternative.intervention.get("block_hosts"):
                missing.append(component.id)
        elif NODE_SOURCES.get(component.node) not in wanted:
            missing.append(component.id)
    return missing


def hostless_connections(report: dict) -> list[str]:
    """
    The connections the capture recorded without a host that sent payload and were not dropped, as O's scope gives
    them: where their data went is unknown. A connection with a host, over TCP, TLS or QUIC alike, is judged by its
    host.
    """
    return [i for c in _captures(report) for i in c.get("hostless") or ()]


def _hosts(report: dict) -> dict[str, dict]:
    """Per host, the connections the capture recorded and those it dropped, as O's scope gives them."""
    out: dict[str, dict] = {}
    for capture in _captures(report):
        for host, counts in (capture.get("hosts") or {}).items():
            mine = out.setdefault(host, {"connections": 0, "blocked": 0})
            mine["connections"] += counts.get("connections", 0)
            mine["blocked"] += counts.get("blocked", 0)
    return out


def _source_imposed(v: Verification, report: dict, component: str, source: str, setting: str) -> dict:
    v.cite("o:scope", ["rt", "net"], "observation", "scopes", "context.instruments")
    status = hook_status(report, source)
    if status not in ("verified", "not_exercised"):
        return {"component": component, "holds": False, "note": f"Loki's verification of {source}: {status!r}"}
    reads = source_reads(report, source)
    for r in reads:
        v.cite(f"o:{r['id']}", r["kinds"], "observation", r["id"])
    mode, _, argument = setting.partition(":")
    if mode == "round":
        wrong = [r["id"] for r in reads if not _rounded(r["proposition"], int(argument))]
        if wrong:
            return {
                "component": component,
                "holds": False,
                "note": f"reads not rounded to {argument} decimals: {wrong}",
                "evidence": wrong,
            }
    if mode == "replace":
        wrong = [r["id"] for r in reads if not _replaced(r["proposition"], source, argument)]
        if wrong:
            return {
                "component": component,
                "holds": False,
                "note": f"reads not handed the imposed value: {wrong}",
                "evidence": wrong,
            }
    note = (
        f"{len(reads)} read(s), each handed the imposed value" if reads else "the application did not read the source"
    )
    return {"component": component, "holds": True, "note": note, "evidence": [r["id"] for r in reads]}


def _recipient_removed(v: Verification, report: dict, entity: str, blocks: list[str]) -> dict:
    v.cite("o:claims", ["net"], "observation", "claims", f"transmits to {entity}")
    v.cite("o:statuses", ["net"], "observation", "statuses", "the sources' part of the network channels' silence")
    open_ = sorted(
        {
            b["method"]
            for s in report.get("statuses") or ()
            for b in s.get("basis") or ()
            if b.get("method") in ("value_matching", "content_inference") and b.get("sources") == "open"
        }
    )
    if open_:
        return {"component": entity, "holds": False, "note": f"the capture's sources are open ({', '.join(open_)})"}
    v.cite("o:scope", ["rt", "net"], "observation", "scopes", "context.instruments")
    hostless = hostless_connections(report)
    if hostless:
        v.unverifiable.append(f"no transmission to {entity}: {len(hostless)} connection(s) without a host")
    claims = transmissions_to(report, entity)
    if claims:
        return {
            "component": entity,
            "holds": False,
            "note": "transmissions to the recipient",
            "evidence": [c["id"] for c in claims],
        }
    mine = {h: c for h, c in _hosts(report).items() if any(under(h, b) for b in blocks)}
    reached = sorted(h for h, c in mine.items() if c["connections"] > c["blocked"])
    if reached:
        return {"component": entity, "holds": False, "note": f"connections to its hosts not dropped: {reached}"}
    dropped = sum(c["blocked"] for c in mine.values())
    return {
        "component": entity,
        "holds": True,
        "note": f"no transmission; {dropped} connection(s) to its hosts dropped",
    }


def _substitution(
    v: Verification, run: Run, report: dict, node: str, hooked: dict, baseline_reads: dict[str, list[int]]
) -> None:
    """
    Whether the app read a substitute of the replaced or removed datum more than without the alternative: at most the
    baseline runs' maximum plus their range (max - min), the variation the baselines show themselves. Identical
    baselines leave no tolerance. A check that does not hold names a substitute (`verify` collects them); a source
    that is not hooked or whose hook could not be installed is an unverifiable part.
    """
    sdk = int(((run.meta.get("device") or {}).get("ro.build.version.sdk")) or 0)
    for substitute in SUBSTITUTES.get(node, ()):
        source = NODE_SOURCES.get(substitute)
        if substitute in CLOSED_FROM and sdk >= CLOSED_FROM[substitute] and source not in hooked:
            continue  # closed to the application by the platform; a hook, where there is one, still counts its reads
        if source is None or source not in hooked:
            v.unverifiable.append(f"substitution by {substitute}: its source is not hooked")
            continue
        if hook_status(report, source) == "unavailable":
            v.unverifiable.append(f"substitution by {substitute}: its hook could not be installed")
            continue
        found = source_reads(report, source)
        for r in found:
            v.cite(f"o:{r['id']}", r["kinds"], "observation", r["id"])
        reads = len(found)
        counts = baseline_reads.get(source) or [0]
        most, tolerance = max(counts), max(counts) - min(counts)
        holds = reads <= most + tolerance
        note = f"{reads} read(s), at most {most} in a baseline run, tolerance {tolerance} (the baselines' range)"
        check = {"node": substitute, "holds": holds, "note": note}
        if not holds:
            check["substitute"] = True
            check["note"] = f"{note}: the application fell back to it"
            check["evidence"] = [r["id"] for r in found]
        v.substitution.append(check)


def _replaced(proposition: dict, source: str, argument: str) -> bool:
    """Whether a read returned the imposed value; a replaced location gives each coordinate its part of it."""
    value = proposition.get("value")
    if source != "location":
        return str(value) == argument
    latitude, _, longitude = argument.partition(",")
    wanted = latitude if str(proposition.get("api") or "").endswith("getLatitude") else longitude
    try:
        return abs(float(value) - float(wanted)) < 1e-9
    except (TypeError, ValueError):
        return False


def _rounded(proposition: dict, decimals: int) -> bool:
    """Whether a read returned the platform's value rounded to the decimals (unchanged values were already so)."""
    value, original = proposition.get("value"), proposition.get("original", proposition.get("value"))
    try:
        return abs(float(value) - round(float(original), decimals)) < 10 ** -(decimals + 3)
    except (TypeError, ValueError):
        return False
