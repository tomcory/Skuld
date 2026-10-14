# Skuld

> Skuld is the Expectation pipeline of the Asgard suite (Expectation dimension of the O/D/E
> framework): purpose-conditioned counterfactual analysis of an app's data practices, resulting in
> E claims.

## Role in Asgard

Skuld compares what an app does in a baseline run with what it does in a counterfactual run in
which a data flow is withheld or changed. Only Heimdall and Loki touch the device:

- **Loki** drives the app in both runs and applies the intervention from its configuration: it
  controls **Heimdall**'s capture (app scope, blocked hosts) and instruments the app with Frida
  (a data source passed through or changed). Skuld asks Loki for runs through Loki's command line
  (`loki -c … replay …`, with a configuration that differs in the one setting of the condition) and
  reads the run folders Loki writes.
- **Verðandi** annotates the captured messages. The records pass between the components in the
  formats of **Ratatoskr**.

Skuld owns the vocabulary of interventions, Loki the mechanisms: Skuld's transformation "location
granularity, from precise to two decimals" becomes `instrumentation.sources.location: "round:2"`
in Loki's configuration. Verification is layered: Loki records whether the app was handed what
the settings say; Skuld decides whether the intervention held, which also needs the traffic and,
for a claim, the functional oracle. A run that Loki did not verify is invalid for Skuld.

## Setup

Python 3.12 or newer.

```bash
pip install -e "../Ratatoskr[validate]"   # until Ratatoskr is on its remote
pip install -e ".[dev]"
```

## Usage

```python
from skuld.runs import RunRefused, load

run = load("../Loki/runs/com.example.app/<run id>")  # RunRefused if Skuld cannot rely on it
run.actions  # what was done to the app, Loki's 'action' events
run.source_reads  # what the app read of an instrumented source, and what it was handed
run.changes  # source settings changed during the run, with their times
run.messages  # the captured HTTP messages (captured_http_message)
run.verified  # Loki's verification of the instrumentation; run.verification has the details
```

A run is refused (`RunRefused.reason`) if it did not end in order (`unfinished`), was not captured
or its capture failed (`no_capture`, `capture_failed`; `load(…, capture=False)` does not read the
capture), Loki did not validate its export (`export_not_validated`), the export is not complete
(`incomplete_export`), or its instrumentation record does not conform to Ratatoskr's schemas
(`invalid_record`), which Skuld checks again itself.

## Tests

```bash
pytest
ruff format . && ruff check .
```

One test reads a real run of Loki: `SKULD_RUN_DIR`, or the latest captured and instrumented run in
the sibling `Loki/runs/`. It is skipped if there is none.

## License

GPL-3.0, see [LICENSE](LICENSE).
