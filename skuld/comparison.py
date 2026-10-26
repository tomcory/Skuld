"""
Comparisons: runs of a feature under the baseline and under one alternative, judged by one purpose's oracle.

A comparison takes the valid baseline runs and the valid runs under the alternative whose intervention
was verified. It preserves the purpose if the oracle decides `met` for every run, breaks it if `met`
for every baseline run and `unmet` for every run under the alternative, and is undecided otherwise.
Its trade-off is the difference of the oracle's measurements and of the runs' costs, reported, not
judged; a measurement is worse in a run if it is worse than in every baseline run by more than its
tolerance.
"""

from dataclasses import dataclass, field

from skuld.inputs import Oracle
from skuld.oracles import Decision, worse

#: Runs per configuration below which a comparison's technical uncertainty is raised
MIN_RUNS = 3


@dataclass
class Comparison:
    """
    Attributes:
        worse: Per measurement, in how many runs under the alternative it is worse: 'none', 'some' or 'all'
        unverifiable: The unverifiable parts of the runs under the alternative
        divergence: Per run, the replay's divergences, repairs and skipped actions where any occurred: after the
            feature's path, since a run that departed within it is no run of the feature
        alternating: Whether runs of the two configurations alternate in the sequence of runs
    """

    id: str
    case: str
    purpose: str
    alternative: str
    baseline_runs: list[str]
    alternative_runs: list[str]
    outcome: str
    measurements: dict = field(default_factory=dict)
    worse: dict = field(default_factory=dict)
    costs: dict = field(default_factory=dict)
    unverifiable: list[str] = field(default_factory=list)
    divergence: list[dict] = field(default_factory=list)
    alternating: bool = True

    @property
    def evidence(self) -> str:
        return f"k:{self.id}"

    def technical(self) -> str:
        """
        U_t: low only if Unv is empty, the order alternated and each side has enough runs. A run that departed from
        the recording within the feature's path is no run of the feature; departures after the path are outside it.
        """
        low = (
            not self.unverifiable
            and self.alternating
            and min(len(self.baseline_runs), len(self.alternative_runs)) >= MIN_RUNS
        )
        return "low" if low else "moderate"


def outcome(baseline: list[Decision], alternative: list[Decision]) -> str:
    if all(d.decision == "met" for d in baseline + alternative):
        return "preserves"
    if all(d.decision == "met" for d in baseline) and all(d.decision == "unmet" for d in alternative):
        return "breaks"
    return "undecided"


def compare(
    cid: str,
    case: str,
    purpose: str,
    alternative: str,
    oracle: Oracle,
    baseline: dict[str, Decision],
    under: dict[str, Decision],
    order: dict[str, int],
    costs: dict[str, dict],
    unverifiable: list[str],
    divergence: list[dict],
) -> Comparison:
    """A comparison of valid, verified runs, given as {run id: the oracle's decision}."""
    measurements, worse_in = {}, {}
    for m in oracle.measurements:
        before = [baseline[r].measurements.get(m.name) for r in baseline]
        after = [under[r].measurements.get(m.name) for r in under]
        flags = [worse(v, before, m.better, m.tolerance) for v in after]
        measurements[m.name] = {"baseline": before, "alternative": after}
        worse_in[m.name] = "all" if flags and all(flags) else "some" if any(flags) else "none"
    positions = sorted((order[r], r in under) for r in [*baseline, *under])
    switches = sum(1 for a, b in zip(positions, positions[1:], strict=False) if a[1] != b[1])
    return Comparison(
        id=cid,
        case=case,
        purpose=purpose,
        alternative=alternative,
        baseline_runs=list(baseline),
        alternative_runs=list(under),
        outcome=outcome(list(baseline.values()), list(under.values())),
        measurements=measurements,
        worse=worse_in,
        costs={"baseline": [costs[r] for r in baseline], "alternative": [costs[r] for r in under]},
        unverifiable=sorted(set(unverifiable)),
        divergence=divergence,
        alternating=switches > 1 or min(len(baseline), len(under)) < 2,
    )
