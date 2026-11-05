# SmartMem 第一版开发记录

> 只用占位符、匿名 id 和汇总，不写私有路径、真实序列号、凭证。模板见 [SMARTMEM_PHASE1_TODO.md](../plans/SMARTMEM_PHASE1_TODO.md) D 节。

## 基线

```text
Step: baseline
Input contract/version: docs/plans/SMARTMEM_PHASE1_{IMPL_PLAN,TODO}.md @ main a366c92
Files changed: none (branch feat/smartmem-data-knowledge created from main a366c92)
Tests/commands and observed results:
  python -m pytest --collect-only -q  -> 14 collected, 41 errors, all from
  ModuleNotFoundError: faultevolve (30) / typer (5) / pydantic (3) / fastapi (2) / httpx (1)
  / evaluator (1). Cause: the package was never installed. Resolved by an isolated venv
  outside the repo (Documents/fe-smartmem-venv) with `pip install -r requirements.txt`
  plus `pip install -e .`. Global Python was not modified.
Fixture versus real-data evidence: none yet.
Known limitations:
  - Local Python 3.12.10 with pandas 3.0.6 / numpy 2.5.3, while pyproject only pins
    pandas>=2.2 / numpy>=2.0; pandas 3 behaviour changes are therefore untested upstream.
  - `pyarrow` is NOT in requirements.txt or pyproject, but V1-01 requires Feather tests to
    actually read Feather. Installed in the isolated venv only (25.0.1); adding it as a
    project dependency still needs the data owner's decision.
  - `tests/test_knowledge.py` fails locally for two pre-existing platform reasons:
    `import resource` (Unix-only) and UnicodeDecodeError('gbk') from files opened without
    an explicit encoding. Recorded, not worked around.
  - `git ls-tree -r origin/main benchmark/hdd_mvp` lists no `holdout*` path at all, so the
    protected-test-set rule cannot be violated from this repo's contents.
Commit: baseline
Next step and required user input: V1-01 done locally; V1-05/V1-10 still need the raw data
path, filename-to-unit rule, timezone, outcome coverage cutoff and existing attempt code.
```

## V1-01

```text
Step: V1-01
Input contract/version: SMARTMEM_PHASE1_TODO V1-01; schema = 23 MCELOG_COLUMNS verbatim
Files changed:
  tests/helpers_smartmem.py   (new)
  tests/test_smartmem_fixture.py (new)
Tests/commands and observed results:
  1. Wrote tests/test_smartmem_fixture.py first -> red:
     ModuleNotFoundError: No module named 'tests.helpers_smartmem' (1 collection error)
  2. Implemented the helper -> 3 failures: exact-duplicate count expectation, a
     `.loc[Timestamp]` lookup on a non-index column, and CSV/Feather dtype mismatch
     (datetime64[us, UTC] from CSV parse vs datetime64[ns, UTC] from Feather).
  3. Fixed by canonicalising log_time to datetime64[ns, UTC] in read_unit_file().
  python -m pytest tests/test_smartmem_fixture.py -q  ->  17 passed in 0.80s
  PYTHONHASHSEED=0 / 1 / 12345 -> 17 passed each, so the fixture is order- and
  hash-randomisation independent and never reads today's date.
Fixture versus real-data evidence: fixture only (L0). No real data was touched.
Known limitations:
  - serial_number_type is exposed as an external fact table, not derived from events or
    tickets, because the trusted static source is still an open question; V1-05 must not
    fall back to inferring it from failure tickets (that would leak the label).
  - The fixture is one file per unit under train/, matching the current helper's glob. The
    real directory layout is unconfirmed.
  - events exist up to day 119 while OUTCOME_OBSERVED_UNTIL is day 115 on purpose: it
    models a ticket feed that lags the event feed, which is what censoring exists for.
Commit: (this step)
Next step and required user input: V1-02 normalize_events(); no user input needed.
```

## V1-02

```text
Step: V1-02
Input contract/version: SMARTMEM_PHASE1_TODO V1-02; interface from IMPL_PLAN 5.2
Files changed:
  src/faultevolve/data/__init__.py        (new package)
  src/faultevolve/data/event_schema.py    (new)
  tests/test_event_schema.py              (new)
  tests/test_smartmem_fixture.py          (added a generic-layer x 23-column fixture test)
Tests/commands and observed results:
  1. tests/test_event_schema.py first -> red: ModuleNotFoundError: faultevolve.data
  2. After implementing: 5 failed. All five were my own expectation errors, not the module:
     sorting puts an uppercase fixture id before lowercase ones, one June/January typo, a
     4-row list asserted as 3, and an epoch test that mixed ints with strings (so the column
     was object dtype, not the integer case it meant to exercise).
  3. One more red from a real typo: the dtype literal was written as "datetime64[ns, UTC"]
     with the closing bracket outside the quotes, which is a SyntaxError.
  python -m pytest tests/test_event_schema.py tests/test_smartmem_fixture.py -q -> 34 passed
Decisions taken from observed pandas 3 behaviour (probed, not assumed):
  - tz_localize raises "Cannot infer dst time ..." for ambiguous and "... is a nonexistent
    time ..." for gaps; both are wrapped into EventSchemaError carrying a reason but no value.
  - pd.to_datetime on a column mixing "+08:00" offsets with naive strings silently produces
    NaT, so the mixed case is reported as unparsable instead of being localised twice.
  - pandas 3 infers datetime64[us, UTC] from second-precision ISO text while Feather keeps
    ns; read_unit_file now canonicalises to datetime64[ns, UTC] so CSV and Feather compare.
Fixture versus real-data evidence: generic layer verified against the L0 fixture only.
Known limitations:
  - No numeric-epoch support by design (V1-02 has no unit parameter); if the real export is
    epoch-based this becomes an explicit CLI decision, still an open question for the owner.
  - Profile reports cardinality only; category values are never listed.
Commit: this step
Next step and required user input: V1-03 sampling/labeling/censoring; no user input needed.
```

## V1-00 固定用户输入和参考结果

Files touched:
  docs/runs/smartmem-input-evidence.template.md        (new, instantiated with 2026-10-03 probe evidence)
  docs/runs/smartmem-existing-attempt-analysis.md      (new, anonymous audit of the user's memory line)
Command run: read-only python probes against the user's local dataset copy; no file in that project was
written, and no real serial number is printed anywhere (filenames reported masked as sn_#).

Evidence obtained (all `verified` unless marked):
  - unit identity: file name is `{unit_id}.feather`, parent dir `type_A|type_B` is serial_number_type.
    836/836 tickets join to a log file. A trusted static source for type, so the label cannot leak.
  - raw export is PascalCase, 24 columns: adds MciAddr, has NO integer error_type (string
    error_type_full_name with values like CE.READ / CE.SCRUB), spells Manufacturer correctly.
    => MCELOG_COLUMNS (23 lowercase names, official-doc spelling 'manufacturter') is a DIFFERENT
    schema from the file actually on disk. V1-05 must ship an explicit column mapping layer.
  - ticket columns on disk are sn_name/alarm_time/sn_type, not the documented
    serial_number/failure_time/serial_number_type. Second naming mismatch, same conclusion.
  - LogTime and alarm_time are int64 EPOCH SECONDS.  => hard interface gap against V1-02, which
    deliberately refuses numeric timestamps because the epoch unit cannot be inferred. Decision
    recorded for V1-05: add an explicit, opt-in `epoch_unit` declaration to the entry point rather
    than making normalize_events guess; default stays refuse-with-message.
  - time range: sampled min 1704039628, max 1722387617. Read as UTC the earliest event precedes the
    documented 2024-01-01 window start; read as UTC+8 it lands on 2024-01-01 00:20. So the local
    timezone reading is the self-consistent one, but this is NOT confirmed => `pending`, blocks V1-05/V1-10.
  - tickets stop at 2024-05-31 15:47:45 (max alarm_time); no duplicate sn_name (one failure per unit),
    so §16.3's multi-failure/reset rule can only be covered by the synthetic fixture, never by real data.
  - 152/300 sampled failed units keep logging AFTER the alarm => post-failure events really exist and
    §16.3's "drop first failure and everything after" is load-bearing, not theoretical.
  - exact duplicate rows exist (20/120 files, up to 83 rows) AND same-timestamp-different-address rows
    exist (99/120 files, up to 228 rows) => drop_exact over all raw fields is the only safe policy,
    which is exactly what V1-02 asserts. LogTime is not monotone inside a file (13/16 sampled).
  - per-unit row counts range 2 .. 7519 => row caps and aggregation must be explicit config, not defaults.
  - official precomputed features: type_A 99 columns / type_B 66 (6h window structurally absent),
    71,969 units with features vs 62,224 with raw logs => ~9,745 units can never get self-built features.
  - leaderboard calibration is impossible: Codabench 3586 shows CURRENT ACTIVE PHASE: None (browser-read),
    so metric_spec_status stays provisional and no external submission number exists.

Audit verdict on the existing attempt (file:line references in the analysis doc):
  5 checks passed (no future features, post-failure rows dropped, group key carries no label, no test-set
  reads, no target encoding); 8 protocol conflicts recorded R1..R8, the sharpest being that the old
  pipeline anchors samples on the ticket itself (R1) and never censors (R2), plus a threshold chosen on
  the evaluation set (R3) and random unit-fold CV instead of time extrapolation (R4). One real bug was
  already fixed by the owner on 2026-09-30: the scoring window had been taken from the label window
  (10d) instead of the official 7d (R5). Internal rulers do not validate the alert timestamp (R6),
  so their numbers are protocol upper bounds and must be reported as such.

Kept results: four rulers 0.6022 / 0.4647 / 0.3179 / 0.1925, only the last one answers under the
official protocol; reference config window_d=10, lead_min=15, rows_per_sn=200, n_estimators=400,
lr=0.1, num_leaves=31, min_child_samples=50, drop _6h, label_decay, group_by vendor_pn, agg top5,
pos_weight=0.25.

Commit: this step
Next step and required user input: V1-03 sampling/labeling/censoring; no user input needed.
Open questions owned by 侯辰风: (a) confirm epoch timezone, (b) confirm outcome_observed_until,
(c) whether the official scoring source or A/B aggregation rules exist, (d) whether pyarrow joins
requirements, (e) whether prepare_data.py's hardcoded 2024 split dates may become CLI parameters.

## V1-03 sampling, labeling and censoring

Files touched:
  src/faultevolve/data/event_sampling.py  (new)
  tests/test_event_sampling.py            (new)
  src/faultevolve/data/__init__.py        (exports the sampler surface)
Tests/commands and observed results:
  1. tests/test_event_sampling.py first -> red: ModuleNotFoundError: faultevolve.data.event_sampling
  2. 9 failed / 40 passed after the first implementation: one real bug (pd.DatetimeIndex does not
     take a `unit=` keyword on pandas 3, so the output index construction blew up) and two of my
     own expectation errors.
  3. python -m pytest tests/test_event_sampling.py -q -> 49 passed
  4. PYTHONHASHSEED = 0/1/42 -> 49 passed each, so the sample ids and row order do not depend on
     the interpreter's hash randomisation.
  5. python -m pytest tests/test_dataset_stubs.py -q -> 12 passed. The earlier failure
     test_ssd_prepare_small_fixture was my sparse checkout, not the code: benchmark/ssd_alibaba is
     on origin/main but was outside the cone, and `git sparse-checkout add benchmark/ssd_alibaba`
     fixed it. benchmark/hdd_mvp is still missing for the same reason (its data blobs keep
     interrupting the fetch on this link), which leaves 1 collection error `No module named
     'benchmark.hdd_mvp'`; the other 16 are `No module named 'resource'` (Unix only) and 1 is
     `fastapi` not installed in the isolated venv.
Design points worth reviewing:
  - Anchors are ceiled then de-duplicated (requirement 16.2). Flooring would let a 10:00 sample read
    a 10:07 event; the trap test pins exactly that.
  - Post-failure events are dropped BEFORE anchors are generated, so a failure cannot create its own
    prediction time. Samples whose anchor still lands at or after the failure (possible when ceil
    pushes past it) are removed and counted under post_failure.
  - Two distinct reasons that look similar are kept apart: post_failure_event (an event row was
    discarded) versus post_failure (a candidate sample was discarded). Conflating them would hide
    how much of the stream a unit loses at its failure.
  - max_samples_per_unit subsamples anchors by evenly spaced index over the sorted list, so it is
    deterministic and cannot see labels; the seed field is validated but unused by this step.
  - history_end is the prediction time, not the last event time: the interval is defined as
    (t - lookback, t], and V1-06 feature building re-reads that interval.
Decisions taken from observed behaviour:
  - Numeric epoch columns are refused in three places (events, failures, outcome cutoff) with a
    message that says why: neither s-vs-ms nor the timezone can be inferred. The real export on the
    user's disk is int64 epoch seconds, so V1-05 must declare both explicitly (V1-00 records it).
  - Empty input frames skip the timezone check instead of failing, because an empty DatetimeIndex
    is naive by construction and rejecting it would make "no tickets" impossible to express.
Interface deviation from the section 5 draft, recorded per 16.4:
  - build_labeled_samples gained keyword-only failure_unit_col / failure_time_col /
    outcome_observed_until, and an optional `report` mapping that receives the drop counts. The
    return type stays a single DataFrame as the requirement demands.
Commit: this step
Next step and required user input: V1-04 temporal split; no user input needed.

## V1-04 temporal split and leakage audit

```text
Step: V1-04
Input contract/version: SMARTMEM_PHASE1_TODO V1-04; lead=15m, horizon=7d => gap 7d0h15m
Files changed:
  src/faultevolve/data/temporal_split.py (new)
  tests/test_temporal_split.py           (new)
  src/faultevolve/data/__init__.py       (exports the split surface)
Tests/commands and observed results:
  1. tests/test_temporal_split.py first -> red: ModuleNotFoundError: faultevolve.data.temporal_split
  2. first implementation -> 4 failed / 26 passed: one real bug plus three of my own test bugs.
     - real: the audit counted label_window_crosses_split for rows it had itself marked embargo,
       so the end-to-end run reported 10 phantom violations. A removed row cannot leak; only a kept
       row can. Now the crossing check is restricted to rows labelled train/dev/val.
     - test: I had placed the second row of the dev-embargo test at val_end - gap, which is 92d23h45m
       and therefore already inside val (dev is [70d, 85d), not [85d, 100d)). Rewritten, and the
       design decision it hid is now its own test.
     - test: the naive-timestamp case could not be built at all, because make_sample_id refuses a
       naive prediction time; the fixture now localizes and then strips the timezone instead.
     - test: pandas 3 stores these datetime columns at microsecond resolution, so a "+1 ns"
       overshoot raises on assignment; the history-ends-late case uses +1 microsecond.
  3. python -m pytest tests/test_temporal_split.py -q -> 40 passed
  4. PYTHONHASHSEED = 0/1/7 -> 40 passed each (cold-unit ranking uses sha256, not Python hash()).
  5. python -m pytest tests/test_event_schema.py tests/test_event_sampling.py
     tests/test_temporal_split.py tests/test_dataset_stubs.py -q -> 117 passed
  6. python -m pytest tests/test_smartmem_fixture.py tests/test_discovery_splits.py -q -> 22 passed
  7. A last-mile rename inside select_cold_units (count -> wanted) left one reference stale, so the
     function raised NameError even though the suite had been green moments before. Everything above
     was re-run afterwards: test_event_schema + test_event_sampling + test_temporal_split +
     test_dataset_stubs + test_smartmem_fixture + test_discovery_splits -> 139 passed.
Design points worth reviewing:
  - The 70/15/15 cut is taken over elapsed time with integer percent arithmetic, and each edge is
    floored onto the anchor grid measured from the same absolute origin the sampler ceils onto, so
    a busy first month cannot buy a larger share of the evaluation than a quiet last one.
  - Purge and embargo are one comparison, not two mechanisms: a kept row whose label_window_end
    reaches the start of the following split is marked embargo (equality already counts). Nothing is
    shifted sideways and no row is dropped, so len(samples) is preserved and the report can state
    embargo_removed.
  - The last scored split has no successor, so the gap rule cannot apply to it. Its tail is instead
    protected upfront: suggest_split_boundaries refuses when val_end + lead + horizon exceeds
    outcome_observed_until. Coverage and leakage are handled by exactly one mechanism each.
  - SplitBoundaries carries an optional start (left-closed). Samples before the declared observation
    span become outside rather than silently training data.
  - A cold unit keeps its dev/val rows and loses only its train-window rows (cold_audit). Selecting
    it by sha256(f"{seed}\x1f{unit}") makes the choice blind to input order; being written to a
    separate directory while still training is explicitly not isolation, hence cold_unit_in_train.
  - The report is counts plus ISO boundary strings: json.dumps() succeeds on it and a sentinel unit
    identifier never appears in it, which is what lets V1-07 print it next to a run.
Decisions taken from observed behaviour:
  - suggest_split_boundaries checks that the train window has room for the gap, but does not check
    dev/val widths. A 40d13h span legitimately yields a ~6d dev window whose every anchor is then
    embargoed; that is a data property the audit describes (empty_split) and the CLI must fail on,
    not something the suggestion should refuse with a vague rule. Only train is checked upfront,
    because an empty train window is a caller mistake rather than a property of the stream.
  - audit_temporal_splits recomputes every assignment from the timestamps instead of trusting the
    split_key column, so an adapter that forgot the gap rule is caught rather than believed.
Interface deviation from the section 6 draft, recorded per 16.4:
  - assign_temporal_splits / audit_temporal_splits gained keyword-only cold_units.
  - suggest_split_boundaries is new: the draft left the boundaries to the caller, which would have
    made the 70/15/15 rule untestable and hand-configured.
  - audit returns a fixed key set (passed, violations, splits, embargo_removed, rows, cold_units,
    boundaries, embargo) rather than an open dict[str, object].
Known gap carried forward: V1-03's "cap only after train is assigned" is not closed by the sampler,
  which caps before the split exists. Until V1-06 wires the pipeline, callers that must keep the
  dev/val grid intact should pass max_samples_per_unit=None and cap the train rows downstream.
Commit: this step
Next step and required user input: V1-05 SmartMem adapter. It needs from 侯辰风: the filename-to-unit
  rule, the epoch timezone, the trusted static-attribute source for failure-free units, and
  outcome_observed_until.
```

## V1-05 (part 1) SmartMem reader and field mapping

```text
Step: V1-05, first of three parts (reader + mapping; features; aggregate_events_to_samples)
Input contract/version: SMARTMEM_PHASE1_TODO V1-05; evidence = smartmem-input-evidence.template.md
  section 2.1 (24 PascalCase columns, int64 epoch seconds) and 2.2 (sn_name/alarm_time/sn_type)
Files changed:
  src/faultevolve/tasks/smartmem_data.py (new; the TODO allows reader/features to live here)
  tests/test_smartmem_reader.py          (new)
Tests/commands and observed results:
  1. tests/test_smartmem_reader.py first -> red: ModuleNotFoundError: faultevolve.tasks.smartmem_data
  2. first implementation -> 8 failed / 17 passed, then 3 failed, then 1 failed:
     - real: pd.to_numeric() on a tz-aware datetime column returns int64 nanoseconds, so a Feather
       file with proper timestamps was routed into the epoch branch and demanded an epoch_unit.
       Datetime dtypes are now tested before any numeric probe.
     - real: pandas 3 lets OutOfBoundsDatetime escape errors="coerce" when the unit-scaled value
       leaves the nanosecond range, and again from the final astype. Both are now refused as
       SmartMemDataError naming the declared epoch_unit.
     - real: pd.to_datetime(values, errors="coerce") without a format silently NaTs a value with
       nanosecond precision (2024-04-07 12:00:00.000000001+00:00), which the fixture uses. Parsing
       strings now requires format="ISO8601", which keeps full precision.
     - mine: the empty-stem case raises "has an empty unit id", not an extension error; the test
       expected the wrong word.
     - mine: the fixture ticket table has 6 rows (5 failing units + one duplicate ticket), not 5.
     - mine: read_tickets exposed a tolerance for unreadable alarm times; dropping a ticket would
       silently turn a real failure into a negative sample, so the parameter is gone and tickets
       are strict.
  3. python -m pytest tests/test_smartmem_reader.py -q -> 25 passed
  4. python -m pytest (event_schema + event_sampling + temporal_split + smartmem_reader +
     smartmem_fixture + dataset_stubs + discovery_splits) -q -> 164 passed
Design points worth reviewing:
  - The unit id comes from the file name and nothing else, and only when the name ends in exactly
    one known extension: part-0001.csv.gz is refused rather than read as the serial "part-0001.csv".
  - serial_number_type is read from the parent directory (type_A / type_B), which is a declared
    source; a directory that is not a type directory returns None instead of falling back to the
    tickets, because deriving A/B from tickets leaks which units failed.
  - Every identifier in an error message is masked with anonymize_unit() (sha256, 12 hex). Files,
    rows and column names appear; serial numbers never do. The SENTINEL unit test pins this.
  - Mapping is a table, not a heuristic: the 24 observed names onto the official 23 (including the
    official misspelling manufacturter), MciAddr kept as mci_addr because it has no official slot,
    and an undeclared extra column is refused. manufacturer (correct spelling) is refused with a
    hint, so a silently "fixed" spelling cannot break compatibility.
  - Label-only columns (failure_time, alarm_time, serial_number_type, ...) are refused inside an
    event frame, which is the enforceable half of "never merge tickets into visible features".
  - Same-timestamp-different-address rows survive; only exact duplicate rows are removed, counted in
    report["exact_duplicate_rows"]. This matches the probe: 99/120 units share timestamps, 20/120
    carry exact duplicate rows.
  - A serial_number column inside a file must agree with the file name, or the file is refused.
Decisions taken from observed behaviour:
  - An int64 epoch is an absolute instant. Interpreting it with utc=True does not need a timezone,
    so the section 3 open question ("UTC or UTC+8") does not shift the data; it only changes how the
    official window bounds 2024-01-01..2024-07-31 are written down. Declaring timezone still stays
    mandatory in the API because naive local strings do depend on it and because a report must state
    the basis it was read in. This narrows what 侯辰风 actually has to answer.
  - Rows whose time cannot be parsed are dropped only when the caller declares a threshold; the
    count is reported. Default threshold is 0, so the default behaviour is to fail.
Interface deviation from the section 5.4 draft, recorded per 16.4:
  - read_smartmem_file takes timezone / epoch_unit / max_unparsable_rows / duplicate_policy /
    report as keyword-only arguments; the draft had only fmt and serial_number.
  - Unit extraction is split into unit_from_filename and serial_type_from_path instead of one
    implicit step, so the two declared sources can be tested and refused separately.
Not done in this part: feature groups (5.5), aggregate_events_to_samples(), and the manifest that
  records each feature's source field, window, dtype and missing rule.
Commit: this step
Next step and required user input: V1-05 part 2 features; still needs from 侯辰风 the trusted static
  source for serial_number_type of failure-free units (a directory rule is available now) and the
  window list the official precomputed features used, if the goal is to line up with them.
```

## V1-05 (part 2) 历史窗口特征与特征清单

```text
Step: V1-05, second of three parts (features; the manifest)
Input contract/version: SMARTMEM_PHASE1_TODO V1-05 第 5/6/7 条（计数、多窗口强度、最近间隔、空间
  唯一数与集中度、error_type、parity/retry/burst、缺失与覆盖；静态取 t 及之前最新值；每特征记录
  source/window/dtype/缺失规则）
Files changed:
  src/faultevolve/tasks/smartmem_data.py (FEATURE_GROUPS / FEATURE_MANIFEST / history_features /
    add_history_features, plus the module docstring and __all__)
  tests/test_smartmem_features.py        (new, 23 tests)
Tests/commands and observed results:
  1. tests/test_smartmem_features.py first -> red at import: cannot import name 'FEATURE_GROUPS'
  2. first implementation -> 17 failed / 6 passed. One real bug: Series has no .as_unit(), so the
     ns conversion had to go through pd.DatetimeIndex(...).as_unit("ns").asi8; without it a
     datetime64[us, UTC] column (what pandas 3 infers from Feather here) would have been read as
     nanoseconds.
  3. second run -> 2 failed / 21 passed, both my own test bugs: DataFrame.assign() passes the whole
     frame to a callable, so assign(log_time=lambda s: s + 1d) added a Timedelta to the string
     columns; and .item() on a two-row column raises "can only convert an array of size 1".
  4. python -m pytest tests/test_smartmem_features.py tests/test_smartmem_reader.py -q -> 50 passed
     (23 features + 27 reader, including the two reader tests added after part 1's commit: a
     non-DataFrame argument, and every message staying anonymous across two refuse paths)
  5. python -m pytest (event_sampling + temporal_split + smartmem_reader + smartmem_features) -q
     -> 139 passed
  6. python -m pytest tests -q --continue-on-collection-errors -> 468 passed / 18 failed / 1 skipped
     / 19 collection errors. All 18 failures are the platform ones already recorded in 基线 and none
     touch a file this step changed: 12 want benchmark files the sparse clone never fetched (10
     hdd_protected_files sha checks + card_promotion + 1 doctor check), 3 import the Unix-only
     resource module (discovery_reproducibility, 1 doctor check, knowledge mock run), 3 are
     read_text() opened without an explicit encoding under GBK (jev_screening + 2 knowledge).
Design points worth reviewing:
  - history_features never slices: the caller hands it (t - lookback, t] and the function refuses any
    row after t. That makes the leakage rule testable in one place, and the "append future rows,
    nothing changes" test is then a statement about slicing, not about a hidden filter.
  - Groups are switchable (feature_groups), unknown names are refused rather than ignored, and the
    emitted column order follows the group order, so a knowledge card can name a subset and get
    exactly that subset back.
  - Missing is missing. An empty window gives count 0 but None for every rate, gap, span and static
    field; a zero retryrderrlog is a readable "no mark", not a missing value, and blank burst_info
    is not a distinct pattern. Fabricating 0.0 for an unobserved gap would teach a model that silent
    units are healthy.
  - growth_rate is (recent_half - earlier_half) / event_count, i.e. a shift of share within the
    lookback, hand-checkable as (2-1)/3 on unit-clean. recent_half splits at t - lookback/2.
  - An error type that was not declared increments unexpected_error_type_count and never becomes a
    new column, so a new vendor code cannot silently widen the feature frame between splits. The
    per-type columns are the only names not in FEATURE_MANIFEST, and they are exactly {slug}_count.
  - Static fields take the last non-empty value at or before t from the window, keeping the source
    dtype (manifest dtype records "source"); this is the "latest known configuration" rule, and
    encoding/normalisation stays with the training step, which V1 does not fit on the whole split.
  - add_history_features keeps every sample row, including a unit with no log and no event in the
    window, because dropping a row would move the official F1 denominator.
Interface deviation from the section 5.5 draft, recorded per 16.4:
  - history_features takes prediction_time explicitly: minutes_since_last_event, the recent/earlier
    half split and the growth rate are all measured against t, not against the last row handed in.
  - add_history_features joins events to samples on the unit column and groups the whole log in
    memory; that is the fixture-scale path. The 130 GB path is V1-06's job and must stream one unit
    at a time into the same history_features.
Not done in this part: aggregate_events_to_samples() wrapper (part 3), and any interaction feature
  group - there is no trusted source for the official precomputed window list yet.
Commit: this step
Next step and required user input: V1-05 part 3. Still needs from 侯辰风: the official precomputed
  feature/window list if the goal is to line up with it, and confirmation that error_type values are
  the ce/ue pair and nothing else.
```

## V1-05 (part 3) aggregate_events_to_samples 薄封装

```text
Step: V1-05, third of three parts (the adapter wrapper), which closes V1-05
Input contract/version: SMARTMEM_PHASE1_TODO V1-05 第 8 条（封装通用函数；keyword-only 传时区与覆盖
  截止；旧位置参数保持可读错误）; IMPL_PLAN 5.4 "不得在此重复时间切分算法"
Files changed:
  src/faultevolve/tasks/smartmem_data.py   (aggregate_events_to_samples + window alias resolution
    + timezone declaration; DEFAULT_* window constants; LEGACY_WINDOW_KEYWORDS)
  src/faultevolve/tasks/smartmem_adapter.py (the method delegates; docstring no longer claims stub)
  tests/test_smartmem_samples.py           (new, 23 tests)
  tests/test_dataset_stubs.py              (the obsolete "documented stub" test replaced)
Tests/commands and observed results:
  1. tests/test_smartmem_samples.py first -> red at import: cannot import name
     'aggregate_events_to_samples'
  2. implementation -> 19 passed on the first run, so the expectations were hand-derived but not
     yet proven to bite. Mutation check: with the wrapper's feature call handed a hardcoded
     1-day lookback instead of config.lookback, 2 failed (the hand-counted event_count row and the
     row-by-row comparison against add_history_features), then reverted -> 23 passed. The tests are
     not vacuous on that axis.
  3. python -m pytest (samples + features + reader + fixture + dataset_stubs + temporal_split +
     event_sampling + event_schema) -q -> 207 passed
  4. python -m pytest tests -q --continue-on-collection-errors -> 491 passed / 18 failed / 1 skipped
     / 19 errors. The 18 are the same platform failures recorded in part 2; the count went 468 ->
     491 with these 23 tests.
Design points worth reviewing:
  - The wrapper holds no windowing, labelling, censoring or splitting arithmetic: it builds
    EventWindowConfig + MCELOG_EVENT_SCHEMA, calls build_labeled_samples, then add_history_features.
    split_key comes back empty and an end-to-end test hands the result to suggest_split_boundaries,
    assign_temporal_splits and audit_temporal_splits and asserts report["passed"] on all 9 fixture
    units at once.
  - outcome_observed_until is a required keyword. A negative sample is only honest once follow-up
    coverage reaches the end of its label window, so there is no default that could quietly turn
    "unobserved" into "healthy".
  - Legacy day/minute spellings (lookback_days, lead_minutes, predict_window_days,
    sample_every_minutes, max_samples_per_dimm) are translated, and passing both spellings of one
    window is refused rather than resolved by precedence - a silent winner is how the old attempt's
    numbers stopped being reproducible.
  - Old positional usage still fails with Python's own readable message ("takes 2 positional
    arguments but 3 were given"), which is what 保持旧位置参数可读错误 asked for. The window defaults
    sit in module-level DEFAULT_* constants and an _UNSET sentinel separates "not passed" from
    "passed None", which is a real answer for max_samples_per_unit.
  - Naive log_time / failure_time are refused unless timezone is declared, and numeric epoch columns
    are pointed at read_smartmem_file(), which is the only place that makes a caller state epoch_unit.
    A run therefore always records the time basis it was computed in.
  - error_types defaults to (): no per-type columns are invented when the inventory is still 侯辰风's
    to confirm. Declaring ("ce","ue") adds ce_count/ue_count; an undeclared value counts into
    unexpected_error_type_count instead.
  - Tickets are validated (A/B only) and then used solely as the label source; failure_time,
    serial_number_type, sn_name and alarm_time are asserted absent from the sample frame.
Interface deviation from the section 5.4 draft, recorded per 16.4:
  - read_smartmem_file's frame is the expected input (it must carry serial_number); a frame without
    it is refused instead of assuming one unit, because a mis-labelled join is invisible downstream.
  - add_features=False returns exactly the generic OUTPUT_COLUMNS, which the draft did not consider;
    it exists so the wrapper's added columns can be diffed against a direct add_history_features call.
Known gap carried forward:
  - max_samples_per_unit applies before the split inside the generic sampler, so the fixture test
    passes max_samples_per_unit=None. Train-only capping still belongs to V1-06.
  - add_history_features groups the whole event frame in memory. Fine for fixtures and for one unit
    at a time; the 130 GB path is V1-06's streaming job and must feed the same history_features.
Commit: this step
Next step and required user input: V1-06 chunked IO and resume, then the V1-07 CLI. Still needs from
  侯辰风: outcome_observed_until for the real data, the filename-to-unit rule confirmed against a real
  directory listing, and the trusted static source of serial_number_type for failure-free units.
```

## V1-06 (part 1) 运行清单与恢复判定

```text
Step: V1-06, first of two parts (the manifest layer; io.py follows in part 2)
Input contract/version: SMARTMEM_PHASE1_TODO V1-06 第 3-8 条（opaque 输入身份 / 排序键 config hash /
  先算 SHA256 再原子 checkpoint / resume 三级判定 / 单协调 writer / 无合法 manifest 的输出目录拒绝覆盖、
  原始目录与输出目录互相包含时拒绝）; IMPL_PLAN "130 GB 不能重复读、输出目录紧邻源数据"
Files changed:
  src/faultevolve/data/manifest.py  (new; MANIFEST_VERSION/MANIFEST_NAME/LOCK_NAME/PARTITIONS_DIR,
    EXIT_CONFIG_CHANGED, ManifestError, ConfigChangedError, sha256_file, input_digests, config_hash,
    read_manifest, prepare_run, finish_partition, verify_partitions, plan_resume, writer_lock)
  src/faultevolve/data/__init__.py  (re-exported; the layer still carries no domain vocabulary)
  tests/test_run_manifest.py        (new, 28 tests)
Tests/commands and observed results:
  1. tests/test_run_manifest.py first -> red at import: No module named 'faultevolve.data.manifest'
  2. implementation -> 26 passed / 1 failed. The failure was real and it was my design, not the
     test: plan_resume had been written on top of prepare_run, so an input change raised inside
     prepare_run before plan_resume could report it, and reason="inputs" was unreachable. Rewrote
     plan_resume to read_manifest + compare config_hash and the recorded input digests directly
     (its unused raw_dir parameter went away with it, 6 call sites) -> 27 passed.
  3. Mutation check, two mutations at once: verify_partitions' sha comparison replaced by a constant
     False, and config_hash's sort_keys=True dropped -> 3 failed
     (test_the_config_hash_ignores_key_order_but_not_values,
      test_nested_config_dicts_are_hashed_stably,
      test_a_single_damaged_partition_is_the_only_one_rebuilt), reverted byte-for-byte -> 28 passed.
     So the "rebuild only the damaged partition" and "key order cannot change the identity" claims
     are both actually tested.
  4. Added test_the_manifest_layer_carries_no_domain_vocabulary as a guard for the two new/edited
     files, then proved it bites by appending a "# DIMM" line to manifest.py -> 1 failed, removed ->
     0 occurrences, 28 passed. The generic layer stays domain-free as the other three data modules
     already enforce.
  5. python -m pytest (run_manifest + smartmem samples/features/reader + temporal_split +
     event_sampling + event_schema + dataset_stubs) -q -> 217 passed
  6. python -m pytest tests -q --continue-on-collection-errors -> 519 passed / 18 failed / 1 skipped
     / 19 errors. Identical to the recorded pre-existing environmental baseline (12 want benchmark
     blobs this sparse clone never fetched, 3 import resource, 3 GBK read_text(), 18 platform
     failures); the passing count rose 491 -> 519 with these 28 tests.
Design points worth reviewing:
  - A source file name may be a real unit identifier, so a manifest identifies inputs by content
    digest (inputs.sha256 is a sorted list of digests plus a count) and ManifestError messages quote
    counts and shapes, never a path or a name. sha256_file's own "file does not exist" message says
    so out loud. The test asserts the literal substring "unit-file" is absent from manifest.json.
  - config_hash is sha256(MANIFEST_VERSION \x1f algorithm_version \x1f canonical JSON). Key order,
    nested dict order and dict-vs-tuple spelling cannot move it; the algorithm version and the
    manifest format can, and a changed seed is a config change, not a new dataset (tested).
  - config_hash refuses what it cannot re-hash identically in two environments: a non-JSON value
    (pd.Timedelta -> "convert it to a string, e.g. '5 days'"), NaN/Infinity (json would emit invalid
    tokens), any key whose name smells like a credential, and any string value shaped like a
    filesystem path. A manifest is a shared artifact; a secret pasted into a config would otherwise
    be laundered into it as a hash input.
  - Every write goes name + ".tmp", flush, os.fsync, then os.replace. finish_partition hashes the
    bytes only after they exist and refuses to checkpoint a file that is not there, so a crashed run
    leaves an invisible .tmp instead of a checkpoint claiming a partial partition is complete.
    verify_partitions only ever consults manifest entries, hence .tmp is never counted (tested).
  - Resume has exactly three answers and they are ranked, per the TODO: config drift ->
    ConfigChangedError with exit_code 2 and nothing reused, because that is a different experiment
    (mixing partitions from two configs is a long job's worst outcome); input drift -> reuse [],
    rebuild everything, reason "inputs"; damaged or deleted output -> rebuild only those names,
    reason "outputs"; otherwise reason None. A deleted file is rebuilt rather than re-hashed,
    because "matches the recorded digest" and "was never there" must not share a branch.
  - prepare_run will not adopt a directory it did not create: files present + no manifest -> refuse;
    raw dir == output dir, or either containing the other -> refuse, and the nesting check runs
    before any existence check so the refusal does not depend on what is on disk yet.
  - writer_lock is O_CREAT|O_EXCL per run directory, and a killed process deliberately leaves the
    lock behind: guessing that a dead writer finished its rename is how a corrupted partition gets
    stamped complete. Parallel workers stay outside the lock, each writing its own temp partition;
    only the coordinator finalizes (V1-07's CLI is where that fan-out is wired).
  - A partition entry's name is validated as a relative path ([A-Za-z0-9][A-Za-z0-9._/-]*, no "..",
    no leading /), and its file must resolve inside the run directory, so no name escapes upward.
Interface deviation from the section 5.x draft, recorded per 16.4:
  - plan_resume does not take raw_dir. The TODO phrased resume as "compare input content hash",
    which needs only the digests, and taking a directory nobody reads invited exactly the
    unreachable-reason bug above.
  - read_manifest requires manifest_version == "runmanifest-v1" and all of config_hash,
    algorithm_version, inputs, partitions; a truncated or older-format manifest is refused rather
    than partially trusted.
  - inputs records count + digests only. It does not record bytes or mtimes, because those are not
    identity and an mtime changes when a file is merely copied to another machine.
Known gap carried forward:
  - Nothing consumes the manifest yet. Wiring prepare_run/finish_partition/plan_resume into a real
    partition loop is part 2 (io.py) and V1-07 (CLI), where EXIT_CONFIG_CHANGED must become the
    process exit code.
  - The manifest records digests of files handed to it, not names. An input replaced by a file of
    different content is caught by the digest; one replaced by byte-identical content is the same
    input, which is the intended trade. Identity is by content, so a moved or copied file is still
    recognized; the manifest records no name, because a name may be an identifier.
  - max_samples_per_unit is still applied pre-split inside the generic sampler (train-only capping
    stays open), and add_history_features still groups a whole frame in memory. Part 2 must feed
    chunked units into the same history_features and prove chunk/whole equality.
Commit: this step
Next step and required user input: V1-06 part 2, bounded-chunk reads that keep cross-chunk lookback
  state, external partition sort, and the 1/2-workers plus chunk/whole consistency tests. Still needs
  from 侯辰风: the real directory listing to fix the file-to-unit rule, and whether pyarrow goes into
  requirements (the Feather path currently raises a declared dependency error).
```

## V1-06 (part 2a) 有界分块读取与跨块 lookback 状态

```text
Step: V1-06, second of three parts (chunked reading and carry-over; the external sort and the writer
  coordination follow in part 2b)
Input contract/version: SMARTMEM_PHASE1_TODO V1-06 第 1 条（每文件只读一次或按有界 chunk 读取，跨 chunk
  保留 lookback 所需状态，不能遗漏 chunk 边界窗口）+ 测试要求"分块/整块一致""不能仅对同一个函数调用
  两次当确定性测试"; IMPL_PLAN 130 GB 不得整文件载入
Files changed:
  src/faultevolve/data/io.py        (new; FORMATS/DEFAULT_CHUNK_ROWS, IoError, EventWindow,
    iter_file_chunks, carry_forward, iter_event_windows)
  src/faultevolve/data/__init__.py  (re-exported)
  tests/test_chunked_io.py          (new, 26 tests)
Tests/commands and observed results:
  1. tests/test_chunked_io.py first -> red at import: No module named 'faultevolve.data.io'
  2. implementation -> 19 passed / 5 failed. Four were my test's wrong premises, one was a real
     defect, and each was settled on the evidence rather than by editing whichever was convenient:
     - an empty chunk: pandas 3.0.6 hands back one zero-row frame for a header-only CSV, so a
       caller counting chunks would count a row that is not there. _csv_chunks now skips zero-row
       chunks. Real defect, fixed in the code.
     - test_carry_forward_drops_rows_no_later_window_can_reach expected 19 rows and got 18. The
       hand count was mine and it was wrong: the row sitting exactly on boundary - lookback is
       excluded by the open left edge, which is the documented select_history rule. Fixed the
       expectation, not the rule.
     - a naive time column: the refusal DID NOT RAISE because my fixture CSV round-trips a tz-aware
       column ("...+00:00"), so pd.to_datetime kept it aware. Reproduced standalone and the
       refusal fires; the test now strips the offset on purpose.
     - two pytest.raises matches: pytest matches case-sensitively, so "sort" did not match
       "Sort the file...", and select_history names the column that was asked for, not the column
       the frame has. Both assertions corrected to say what the contract actually is.
  3. Mutation checks, run one at a time so each claim names the test that catches it. The pristine
     file was copied aside first and each mutation was reverted from that copy:
     - four mutations together (backwards-chunk guard replaced by False, carry_forward returning
       every row, the chunk list materialised eagerly, the zero-row chunk filter removed) -> 8
       failed against the 24 tests of that round; reverted from the copy -> 24 passed.
     - the zero-row chunk filter removed on its own -> 1 failed
       (test_an_empty_file_yields_no_chunks_and_no_windows).
     - carry_forward returning every row on its own -> 7 failed, including
       test_carried_rows_stay_bounded_by_the_lookback.
     - the eager materialisation, on its own -> 0 failed with my first laziness test in place. That
       test was lying: it counted prepare() calls, and prepare runs per chunk whether the reader was
       drained eagerly or not, so the assertion held under a mutation that plainly breaks the
       bounded-memory requirement. It was replaced by three claims that can bite -
       test_no_chunk_or_window_holds_more_rows_than_the_bound_allows (200 rows at chunk_rows=7: no
       chunk larger than 7, no window larger than 7 + the three rows a one-hour lookback reaches,
       and the reader is a generator), test_each_row_is_normalised_exactly_once (a carried row is
       never prepared a second time), and test_the_consumer_pulls_one_chunk_at_a_time, which stands
       in the chunked CSV reader's shoes and records each chunk as it is produced. Re-running the
       eager mutation then failed that test, and reverting it returned to green; re-running the
       carry mutation failed the new bounds test. Both replacements are therefore proven to bite.
  4. python -m pytest tests/test_chunked_io.py tests/test_run_manifest.py -q -> 54 passed
  5. python -m pytest (chunked_io + run_manifest + smartmem samples/features/reader + temporal_split
     + event_sampling + event_schema + dataset_stubs) -q -> 244 passed
  6. python -m pytest tests -q --continue-on-collection-errors -> 545 passed / 18 failed / 1 skipped
     / 19 errors. Same pre-existing environmental baseline as part 1 (12 benchmark blobs a sparse
     clone never fetched, 3 import resource, 3 GBK read_text(), 18 platform failures); 519 -> 545.
Design points worth reviewing:
  - The carry rule IS the window rule: carry_forward is a thin wrapper over select_history, so
    "a chunk boundary lost my window" cannot be caused by two rules disagreeing. The equivalence
    test proves it for every prediction time in the fixture and for chunk sizes 1, 2, 3, 5 and 12,
    which is a statement about the carry bound, not about the sampler.
  - Chunk bounds are in rows, not bytes, because the windows are in time. A chunked CSV cannot be
    type-inferred per chunk - the same column can look numeric in one chunk and blank in the next -
    so csv chunks arrive as text and the caller's prepare() is where types and the timezone decision
    are declared. The generic layer refuses a naive time column instead of assuming UTC.
  - A chunk that starts before the previous chunk ended is refused, and the reason is the carry
    bound: rows are kept only down to boundary - lookback, so a backwards chunk would be handed a
    window whose history was already dropped. Rows unordered *within* a chunk are fine, because the
    layer sorts and the check compares chunk minima to the previous boundary. A file that trips this
    is part 2b's external-sort input, not something to stream and hope.
  - The stream is lazy and that is now a tested property, not an assumption: the consumer pulls one
    chunk at a time, proved by standing in the chunked reader's shoes and recording production.
    Counting prepare() calls, which is what I tried first, does not prove it - see the mutation
    result above.
  - Feather is streamed with pa.ipc.open_file + get_batch + a zero-copy slice, so chunk_rows rows
    are converted at a time and a writer that produced one big batch still yields bounded chunks; a
    missing pyarrow surfaces as an IoError naming the dependency rather than a skipped test.
  - EventWindow carries rows (carry + new, sorted), new_rows, boundary and carry_count. Consumers
    must emit prediction times only from new_rows, otherwise a carried row is sampled twice; that is
    why the split is visible instead of one merged frame.
Interface deviation from the section 5.x draft, recorded per 16.4:
  - iter_event_windows takes a caller-supplied prepare() instead of a fmt+timezone bundle, so epoch
    units and zone declarations stay in the domain layer where read_smartmem_file already makes them
    explicit.
  - Nothing here names the manifest: iter_event_windows streams, it does not checkpoint. The loop
    that pairs them is part 2b/V1-07, which keeps the streaming layer free of run-directory policy.
Known gap carried forward:
  - No external sort and no workers/coordinator yet, so the TODO's 乱序超大文件 and 1/2 workers items
    are still open for part 2b, together with the space-needed report.
  - read_smartmem_file still reads a whole per-unit file at once. Fine for one unit and for
    fixtures; a single 30 GB file must go through iter_event_windows, and the SmartMem-side
    chunk/whole feature equality test belongs to part 2b.
  - chunk_rows bounds rows, not bytes: an extremely wide chunk is still big. Part 2b should state
    the byte estimate it implies where the plan reports workspace space.
Commit: this step
Next step and required user input: V1-06 part 2b, the time-ordered external partition sort, worker
  writers plus the single coordinating finalize, and the space-needed report on failure. Still needs
  from 侯辰风: the real directory listing (chunk size and partition count are guesses until then).
```

## V1-06 (part 2b) 分区写出：一个协调者、独立临时文件、按摘要恢复

```text
Step: V1-06, third of three parts. Scope narrowed on purpose: this part is the writer coordination
  and the resume agreement; the time-ordered external sort and its space-needed report move to part
  2c, because a sort is a second algorithm and deserves its own red tests rather than riding along
  with a checkpoint change.
Input contract/version: SMARTMEM_PHASE1_TODO V1-06 第 5/7 条（分区完成后算输出 SHA256 再原子写
  checkpoint，失败 .tmp 不能算完成；一个输出目录同时只允许一个协调 writer，workers 写独立临时分区，
  最终协调归并）+ 测试要求"人为中断、损坏文件、输入修改、seed 改变、1/2 workers 一致；不能仅对同一个
  函数调用两次当确定性测试"
Files changed:
  src/faultevolve/data/io.py        (PartitionJob, write_partitions, module docstring widened)
  src/faultevolve/data/manifest.py  (check_partition_name made public for writers, re-exported)
  src/faultevolve/data/__init__.py  (re-exported)
  tests/test_partition_writer.py    (new, 19 tests)
  tests/test_chunked_io.py          (guard message now names the file it checked)
Tests/commands and observed results:
  1. tests/test_partition_writer.py first -> red at import: cannot import name 'PartitionJob' from
     faultevolve.data.io
  2. implementation -> 16 passed / 1 failed, and the failure was mine: the test matched "twice"
     while the message the code promises says "two jobs both write partition ...". Assertion
     corrected to quote the contract, not the wording I happened to type.
  3. Three claims the first suite could not falsify. Each was found by trying to break the code in
     the exact place the claim lives, not by reading it again:
     - the up-front name check was untested. test_a_partition_name_cannot_escape_the_run_directory
       passed even with the check deleted, because finish_partition validates the name too: the
       refusal still arrived, but only after the file had been written outside partitions/ and after
       build() had run. The test now also requires builder.calls == [] and no *escape* path anywhere
       under the run directory. Mutation M2 then fails it.
     - "a failed worker cleans up its own .tmp" was vacuous: the fixture fails inside build(), i.e.
       before any temp file exists, so rglob("*.tmp") was trivially empty. Added a crash that
       happens after the bytes were written - a directory sitting where the partition file belongs,
       so the rename is refused. Mutation M4 then fails it.
     - workers=2 was consistent but not proven concurrent: a fully sequential implementation would
       pass every digest comparison. Added a test where two builds must meet at a
       threading.Barrier(2), which a serial producer can never do. Mutation M7 then fails it, after
       the barrier times out rather than after a sleep I would have had to guess.
  4. Mutation checks, one mutation per run, io.py restored from a pristine copy and the restore
     verified by sha256 equality each time:
     M1 reuse decided by mere existence     -> 2 failed: test_a_damaged_partition_is_the_only_one_
        rebuilt_on_a_rerun, test_a_reused_partition_is_checked_by_hash_not_by_mere_existence
     M2 no name validation before writing   -> 1 failed: test_a_partition_name_cannot_escape_the_
        run_directory
     M3 duplicate partition name accepted   -> 1 failed:
        test_two_jobs_cannot_write_the_same_partition
     M4 no temp cleanup after a crash       -> 1 failed: test_a_worker_that_crashes_after_writing_
        leaves_no_temp_file
     M5 str(exc) copied into the report     -> 1 failed:
        test_a_failed_partition_is_reported_without_renaming_its_error_message
     M6 config/input guards moved after the writes -> 2 failed: the two "stops a rerun before any
        partition is produced" tests
     M7 workers>1 still produces one at a time -> 1 failed: test_two_workers_produce_two_partitions_
        at_the_same_time
     M8 coordinator does not claim the run directory -> 1 failed: test_only_one_coordinator_may_
        write_partitions_at_a_time
     restored -> 19 passed.
     The first driver run also caught a hazard of my own tooling: it rewrote io.py with LF endings,
     the sha comparison refused it ("restore did not reproduce the pristine io.py"), and the file was
     put back from the backup. Left unfixed, that would have landed as a whole-file diff in a commit
     whose real change is 180 lines.
  5. python -m pytest tests/test_chunked_io.py tests/test_partition_writer.py
     tests/test_run_manifest.py -q -> 73 passed
  6. python -m pytest (chunked_io + partition_writer + run_manifest + smartmem samples/features/
     reader + temporal_split + event_sampling + event_schema + dataset_stubs) -q -> 263 passed
  7. python -m pytest tests -q --continue-on-collection-errors -> 564 passed / 18 failed / 1 skipped
     / 19 errors. Same pre-existing environmental baseline (12 benchmark blobs a sparse clone never
     fetched, 3 import resource, 3 GBK read_text(), 18 platform failures); 545 -> 564.
Design points worth reviewing:
  - A worker only ever names its own output file; the one process holding the writer lock is the only
    thing that calls finish_partition. That is what makes "checkpoint describes bytes that were
    hashed" structural instead of a convention: a worker cannot reach the manifest at all.
  - Reuse requires both a recorded status of complete AND the file re-hashing to the recorded digest,
    so an interrupted copy of a partition is rebuilt rather than trusted. Existence-based reuse is the
    failure this whole part exists to prevent.
  - Manifest writes happen in sorted partition-name order after production, so workers=1 and workers=2
    are compared on identical digests. The 1/2 test writes into two separate run directories - a
    second call on the same directory would have been a resume test, not a determinism test, which is
    exactly the "不能仅对同一个函数调用两次" trap in the TODO.
  - The config and input guards run inside the lock and before any build(), so extending a stale
    experiment costs a hash instead of a rebuild. ConfigChangedError keeps exit_code 2 for V1-07.
  - A failure is reported as {"name", "error": <exception type name>}. str(exc) is deliberately not
    stored: the fixture raises OSError("disk full while writing /home/someone/raw/
    unit-serial-123456.csv"), and a report that carried that message would have published a unit
    identifier into a shared manifest directory.
  - Duplicate names are refused before anything is produced: under 2 workers, two jobs on one name
    overwrite each other and the single checkpoint describes whichever finished last.
  - write_partitions returns its report instead of raising on a partial failure, because the resume
    story is the point: one broken partition must not cost the other 399.
Interface deviation from the section 5.x draft, recorded per 16.4:
  - write_partitions takes PartitionJob(name, build) rather than frames or a reader. The streaming
    layer stays free of run-directory policy and the caller decides what a partition contains; the
    zero-arg build is also what makes a retry safe, since it can be called again from scratch.
  - manifest.check_partition_name is public now. Keeping it private meant the only validation of an
    escaping name happened after the bytes were already on disk.
  - No fmt parameter for output: partitions are csv. The TODO asks for readable resume, a second
    writer path would double the byte-digest surface, and a 40-130 GB csv is what the plan streams.
Known gap carried forward:
  - The external time-ordered sort for out-of-order huge files, and the workspace-space report on
    failure, are part 2c. Today an out-of-order file is refused by iter_event_windows, not sorted.
  - Concurrency is proven, throughput is not. ThreadPoolExecutor workers share the GIL, so a build
    that is pandas-heavy gains less than an IO-heavy one; nothing here has been measured on 130 GB.
  - No automatic retry of a failed partition: the rerun is the retry, which is the cheap and honest
    design but means a transient failure needs an operator (or V1-07's CLI loop) to act on it.
  - Nothing bounds rows per partition or checks the train-only sample cap; that guard belongs to the
    SmartMem-side caller, as it did in V1-05.
Commit: this step
Next step and required user input: V1-06 part 2c (external sort + space report, and the SmartMem-side
  chunk/whole + 1/2-workers feature equality), then V1-07's prepare CLI. Still needs from 侯辰风: the
  real directory listing and file sizes (chunk_rows and the partition count are still guesses), plus
  the window-bound convention (UTC or UTC+8) before any real partition set is worth hashing.
```

## V1-06 (part 2c) SmartMem 侧分块与整块一致：一条归一化策略两条路径

```text
Step: V1-06, fourth slice. This one closes the TODO's 分块/整块一致 test requirement on the domain
  side. The external time-ordered sort and its workspace-space report move to part 2d; they are a
  second algorithm and the streaming path is only usable once the domain has one normalisation
  policy, which is what this step builds.
Input contract/version: SMARTMEM_PHASE1_TODO V1-06 第 1 条 + 测试要求"分块/整块一致"; V1-05 known gap
  "add_history_features still groups a whole frame in memory (must be fed per-unit streamed rows)"
Files changed:
  src/faultevolve/tasks/smartmem_data.py (prepare_smartmem_chunk; read_smartmem_file now delegates
    to it instead of carrying its own copy of the rules)
  tests/test_smartmem_chunked_equivalence.py (new, 11 tests)
Tests/commands and observed results:
  1. tests/test_smartmem_chunked_equivalence.py first -> red at import: cannot import name
     'prepare_smartmem_chunk' from faultevolve.tasks.smartmem_data
  2. implementation -> 9 passed / 2 failed, both my test's own bugs: a helper re-formatted a column
     it had already turned into text (.dt on a string column), and Timedelta / Timedelta is a float,
     so .total_seconds() on it does not exist. Fixed the test, not the code.
  3. Seven mutations, each restored from a freshly written backup whose sha256 was re-checked after
     the restore:
     N1 carry nothing across a boundary        -> 5 failed, incl. all three parametrised
        test_streamed_history_features_equal_the_whole_file_for_every_prediction_time cases and the
        feather/csv copy. The equality tests are not decoration: without the carry they see different
        features, not merely slower runs.
     N2 new_rows includes the carried rows     -> 2 failed (every row arrives exactly once; the
        one-lookback-plus-a-chunk bound)
     N3 normalisation keeps every duplicate    -> 1 failed (the split-duplicate test asserts the
        whole file is 9 rows, so the reader's policy is checked through the delegation)
     N4 the reader stops passing its timezone  -> 1 failed (a naive column must refuse in BOTH paths;
        this is the test that pins "one policy, two paths" rather than two similar policies)
     N5 a second unit inside a chunk allowed   -> 1 failed (the identity refusal, and the message is
        asserted to carry the hashed id, not the serial)
     N6 the unparsable threshold ignored       -> 1 failed
     N7 the window-level dedup repair no-oped  -> 1 failed, which is the only thing that proves the
        repaired path is a repair and not an accident of the fixture
  4. python -m pytest (chunked_equivalence + smartmem reader/features/samples/fixture + chunked_io +
     partition_writer + run_manifest + event_schema + temporal_split + dataset_stubs +
     adapter_registry + engine_task_agnostic) -q -> 256 passed
  5. python -m pytest tests -q --continue-on-collection-errors -> 575 passed / 18 failed / 1 skipped
     / 19 errors. Same pre-existing environmental baseline; 564 -> 575.
Design points worth reviewing:
  - The reason to split prepare out of read_smartmem_file is not tidiness: until both paths called
    one function, a chunked read could have quietly differed on the timezone declaration, the
    unparsable-row threshold or the dedup rule, and nothing in the suite would have said so. N4 is
    the mutation that shows the delegation is load-bearing.
  - Exact duplicates share an instant, so a window that holds one holds both. That is why per-chunk
    dedup is unsound on its own (a boundary can split the pair) and why the repair - dedup the
    assembled window - is nevertheless equivalent to whole-file dedup for every feature. The test
    demonstrates the hole first (event_count + 1) and then the repair, instead of only testing the
    version that passes.
  - A chunked consumer serves each prediction time from the first window whose boundary reaches it.
    That rule plus the carry bound is what makes the feature dicts identical; the same test also
    bounds window.rows at one lookback plus one chunk, so a consumer can reason about memory.
  - The streamed identity check names the declared unit only as its irreversible hash, so a chunk
    that turns out to hold a second serial number cannot leak either one into a log.
Interface deviation from the section 5.x draft, recorded per 16.4:
  - prepare_smartmem_chunk takes the unit as an argument instead of deriving it from a path. The
    generic streaming layer must not know about file naming, so read_smartmem_file supplies what
    unit_from_filename decided and the chunk path passes the same value through.
  - No duplicate_policy value was invented for "dedup the window": the repair is the consumer's call
    to normalize_events, so the two layers keep one vocabulary instead of the reader growing a third
    policy that only means something when streaming.
Known gap carried forward:
  - External sort for out-of-order files and the workspace-space report: part 2d. An out-of-order
    file is still refused, not sorted.
  - aggregate_events_to_samples still builds samples from a whole per-unit frame. The chunked path
    is proven for history features; wiring sampling+censor+split through windows is V1-07's CLI job,
    and per real evidence a unit file is ~2 MB on average, so this is not the 130 GB blocker.
  - dedup-the-window costs one extra pass over the assembled rows per window; not measured against
    the whole-file path on a large unit.
Commit: this step
Next step and required user input: either V1-06 part 2d (external sort + space report) or V1-07's
  prepare CLI; the CLI is the one that makes the milestone demoable, so it goes first unless 侯辰风
  says the real files are out of time order. Still needs from him: the real directory listing, the
  window-bound convention, and the coverage end date.

## V1-07 prepare CLI: 退出码契约、两条输出通道、审计闸门

```text
Step: V1-07. benchmark/smartmem/prepare_data.py stops being a stub and becomes the only place where
  the reader, the sample builder, the split audit, the run manifest and the partition writer meet.
  Everything before this step was a library nobody could run; this is the step that makes the
  milestone demoable, and it is also the first step whose output is a contract (exit codes and one
  parseable JSON object) rather than a frame.
Input contract/version: SMARTMEM_PHASE1_TODO V1-07 (统一退出码; JSON 模式 stdout 只输出一个可解析
  JSON, 进度走 stderr 且脱敏; 真实数据缺时区或覆盖截止时停在明确缺项, 不能默认 UTC 以掩盖不确定性);
  IMPL_PLAN section 7 for the flag list; PREP_VERSION = "smartmem-prep-v1" is the algorithm version
  the manifest hashes with, so a later CLI change must bump it rather than silently reuse a run dir.
Files changed:
  benchmark/smartmem/prepare_data.py (52-line stub -> 895 lines: Options dataclass, Console,
    discovery, boundary parsing, three run modes, parser, main)
  tests/test_smartmem_prepare_cli.py (new, 25 tests)
  tests/test_dataset_stubs.py (the stub test moved off pytest.raises(NotImplementedError)
    onto the real contract: a run without confirmed boundaries exits 1 and creates nothing)
Tests/commands and observed results:
  1. Red first, and this time the red is reproducible rather than asserted: after writing the 25
     tests I swapped the committed stub back in with
     `git show HEAD:benchmark/smartmem/prepare_data.py` and ran the file against it ->
     25 failed / 0 passed in 1.98 s, for three distinct reasons:
       SystemExit: 2  (argparse: the stub had no --timezone / --split-config / --profile-only)
       FileNotFoundError: missing .../raw_tmp/train (the stub looked in one directory only)
       NotImplementedError from main (no pipeline existed)
     Restored by byte copy and re-verified (md5 6da8b4e7..., 37 passed).
  2. implementation -> 11 failed / 6 passed. All eleven were my test's own bugs, not the code's:
       CaptureResult has .out/.err, not .stdout/.stderr; capsys.clear() does not exist here.
       two tests wrote the SAME split-config filename that the argv() helper had just rewritten, so
         both silently used the default config and passed for the wrong reason - renamed late.yaml /
         epoch.yaml. This is the nastiest class of bug: a green test that tests nothing.
       write_text("\n".join(rows)) turned the fixture from CRLF to LF and shrank it, so
         the "same-size silent edit" tamper tripped the listing fingerprint and exited 2 instead of
         the intended 1. Rewritten with read_bytes/write_bytes plus an explicit len() assertion, and
         the size-changing case became its own positive test.
     Fixed the tests, not the code.
  3. One test expectation was wrong about the design, not about the code: `--max-files 2` as a real
     run exits 1 because empty_split=2 is a genuine audit violation - a two-unit slice cannot fill
     dev and val. Kept the behaviour, split the claim in two: a dry-run knob test (files/partitions
     only) and a test that pins "a truncated slice fails the audit instead of quietly scoring a
     split that holds two units".
  4. Two real code bugs found by the tests: _estimate_span read prediction_time out of an EVENT
     frame
     (it must use MCELOG_EVENT_SCHEMA.time_col, and a later edit deleting the assignment turned it
     into a NameError that made the mistake obvious); and the first _dry_run validated the suggested
     bounds against the config's coverage cutoff, so a dry run refused to report a suggestion while
     the operator was still deciding how far the follow-up reaches - the estimate is now checked on
     its own with outcome_observed_until=None and the config is validated separately.
  5. Twenty-four mutations, each applied to a byte-exact pristine copy, one at a time, restored
     after every run (final check: TARGET bytes == pristine bytes, suite green):
     argparse-error-exits-2              -> 1 failed (test_an_unknown_format_is_an_input_error...)
     args-error-not-caught               -> 1 failed (same: exit 1 for a bad flag is a claim)
     config-drift-says-input             -> 3 failed (the three resume-drift tests)
     any-error-says-config               -> 10 failed
     no-follow-up-coverage-check         -> 1 failed (the outruns-the-follow-up test)
     epoch-number-accepted               -> 1 failed (test_an_epoch_number_in_the_split_config...)
     timezone-not-validated              -> 1 failed (the unknown-timezone test)
     free-space-not-checked              -> 1 failed (test_a_declared_space_floor_is_enforced...)
     duplicate-unit-allowed              -> 1 failed (test_a_unit_listed_twice_stops_before...)
     listing-fingerprint-is-a-constant   -> 1 failed
     listing-not-in-config-hash          -> 1 failed
     recorded-directory-needs-no-resume  -> 1 failed (test_a_recorded_run_directory_needs_resume...)
     partial-failure-looks-fine          -> 1 failed (exit 3 path)
     audit-violation-still-records-audit -> 2 failed
     stdout-is-always-json               -> 1 failed (see the unproven-claims note below)
     progress-goes-to-stdout             -> 4 failed
     failure-goes-to-stdout              -> 9 failed
     dry-run-writes-a-run-directory      -> 2 failed
     profile-only-also-builds-samples    -> 1 failed (list(recorded) == ["profile"])
     cold-fraction-is-ignored            -> 1 failed (test_cold_units_are_withheld_from_train)
     max-files-is-ignored                -> 2 failed
     json-failure-claims-success         -> 1 failed (only after the test was strengthened)
     worker-count-enters-the-config-hash -> 1 failed (only after the test was strengthened)
  6. python -m pytest tests/test_smartmem_prepare_cli.py tests/test_dataset_stubs.py -q -> 37 passed
  7. the data-layer set (prepare_cli + dataset_stubs + smartmem reader/samples/features/fixture/
     chunked_equivalence + chunked_io + event_schema + discovery_splits + run_manifest +
     partition_writer + temporal_split + knowledge) -> 3 failed / 335 passed / 1 skipped, the three
     being the pre-existing test_knowledge engine-string and mock-run failures
  8. python -m pytest -q --continue-on-collection-errors -> 18 failed / 600 passed / 1 skipped /
     19 errors. Same environmental baseline as before this step (18/19), passed 595 -> 600.
Claims that were NOT provable until the mutation pass (this is the part worth reviewing):
  - "in JSON mode a failed run still emits one object carrying the real exit code" survived
    json-failure-claims-success: nothing read payload["exit_code"] on a failure, so a failure object
    could have printed "exit_code": 0 and the whole suite stayed green. Added that assertion to
    test_a_failing_unit_exits_three_and_reports_only_the_partition_name.
  - "workers decides how a run happens, not what a partition holds" was written in the
    _config_payload docstring and was not tested: worker-count-enters-the-config-hash survived,
    because test_the_worker_count_changes_nothing_about_the_bytes_written compares two SEPARATE run
    directories and therefore never reaches the resume/drift path. The resume test now runs its
    second pass with --workers 2, which is also the practical claim (a bigger machine must reuse
    yesterday's bytes instead of looking like a new experiment).
  - "human mode prints a summary rather than a JSON blob" had no test at all before the pass;
    stdout-is-always-json survived until test_a_small_fixture... asserted the captured stdout does
    not start with "{" and does contain "sample partition".
Design points worth reviewing:
  - Stdout has exactly two writers in the module - Console.emit and Console.fail - and progress plus
    the human-readable error line go to stderr. The contract is a property of the structure, not of
    each call site remembering, which is why one mutation (print to stdout) broke four tests instead
    of one.
  - The CLI does not implement any leakage rule. It reads the written partitions back, hands the
    assembled frame to audit_temporal_splits and obeys the verdict, so there is one policy in the
    repo rather than a copy in the CLI that can drift from it. A failed audit exits 1 and records no
    audit/summary, because a summary of a run that did not pass is not evidence.
  - Input identity is split in two deliberately: the ticket is content-hashed always (836 rows), the
    130 GB of event files is fingerprinted by hashed unit name + size (a stat per file, no read).
    Both are re-checked on resume; --hash-inputs opts into hashing every event file, which is the
    only way to notice a same-size silent edit, and the two branches are pinned by two tests that
    state which one catches what.
  - A bad command line must come back as exit 1, because exit 2 here means "the config changed and
    your resume is stale" - a collision argparse would create by exiting 2 on usage errors itself.
    Hence _Parser.error raising _ArgsError instead of calling SystemExit.
  - Nothing a failing worker says is printed: a job reports {"name", "error": type name}, every unit
    id goes through anonymize_unit, and test_the_manifest_names_no_unit asserts the written manifest
    contains neither the sentinel serial nor the literal "unit-".
Interface deviation from the section 7 draft, recorded per 16.4:
  - Added --units-per-partition (default 64) and --profile-only; section 7 does not name either. 64
    is my documented assumption from the ~2 MB average unit in the small fixture, not a measurement
    on the real package.
  - --max-samples-per-dimm keeps section 7's spelling even though the generic layer refuses the word
    DIMM: this file is domain code, so the flag stays as the plan writes it and maps onto
    max_samples_per_unit.
  - payload["written"]/["reused"] are scoped to sample partitions; the audit partition reports its
    own "audit_reused". A resume therefore prints written: [] even though it rewrote the audit - a
    caller parsing the JSON must not read that as "nothing happened".
  - A partial partition failure exits 3 and writes no audit; a failed audit exits 1. Section 7 lists
    both codes but does not say whether an audit failure is an input error or a partial failure; I
    called it an input error, because the outputs exist and are simply not a usable evaluation set.
Known gap carried forward:
  - No external sort yet: an out-of-order unit file is refused by the reader, not sorted. V1-06
    part 2d remains owed.
  - aggregate_events_to_samples still builds a unit's samples from a whole in-memory frame. The
    chunked path is proven for history features only; a 130 GB run is fine per-unit (~2 MB average)
    but the CLI would still hold one unit's events at a time, which is the documented limit.
  - --hash-inputs is exercised on the small fixture; its real cost on 130 GB is argued (one
    sequential pass) and not measured.
  - The layout is assumed from the plan: train / type_A / type_B queues, ticket.csv under
    failure_ticket.csv names, feather or csv per unit. The tests prove the shape handling and the
    refusals, not that the real package matches. 侯辰风's listing is still the missing evidence.
Commit: this step
Next step and required user input: V1-08, the SM-* knowledge pack (sources.yaml, cards.jsonl,
  expert.md) - the plan's "交付知识" half, which no code can substitute for. Still needs from 侯辰风:
  the real directory listing and ticket columns, the window-bound convention (UTC or UTC+8), the
  confirmed split boundaries with a real coverage end date, whether a same-size silent edit may pass
  unnoticed without --hash-inputs, and the official precomputed feature/window list.
```

## V1-08 SM-* 知识包：卡片必须有出处、适用条件与风险

```text
Step: V1-08. benchmark/smartmem/knowledge/ becomes a real knowledge pack: 23 cards, 11 sources,
  expert.md, a pack README, plus benchmark/smartmem/knowledge_check.py - the validator that owns the
  rules the generic loader does not. evolve.yaml flips knowledge.enabled to true, so this is the
  first step where the phase's output is something an LLM agent reads, not something a human reads.
Input contract/version: SMARTMEM_PHASE1_TODO V1-08; IMPL_PLAN section 8 (原则 8.1 / 文件 8.2 /
  主题 8.3 / 既有尝试 8.4 / 配置 8.5) and 10.2 (知识测试). Loader schema unchanged on purpose:
  REQUIRED_FIELDS/OPTIONAL_FIELDS/VALID_CATEGORIES come from faultevolve.knowledge.loader, so this
  pack is data, not a new format.
Files changed:
  benchmark/smartmem/knowledge/cards.jsonl (new, 23 cards, 8 of 9 loader categories used)
  benchmark/smartmem/knowledge/sources.yaml (new, 11 entries with url + retrieved_via + date)
  benchmark/smartmem/knowledge/expert.md (new, 证据从哪来 / 数值可读性 / 8 条开放问题)
  benchmark/smartmem/knowledge/README.md (new, 约定 + 校验命令 + 明确不具备的能力)
  benchmark/smartmem/knowledge_check.py (new, 280 lines)
  benchmark/smartmem/evolve.yaml (knowledge: enabled true, dir knowledge, k 4, max_per_category 2)
  tests/test_smartmem_knowledge.py (new, 40 tests)
Tests/commands and observed results:
  1. Red reproduced without touching this working tree: `git worktree add ../fe-v108-red HEAD` (read
     only, removed afterwards), copy the new test file in, run it there.
       stage 1 (as committed): ImportError: cannot import name 'knowledge_check' -> collection error.
       stage 2 (validator copied in, pack absent): 12 failed / 28 passed - the four file-existence
         tests, the counts, the retrieval tests and the evolve.yaml test.
     The 28 that already passed are the negative-pack tests, which build their own tmp pack; that is
     the intended split: rules are testable without the artefact they police.
  2. Suite: 18 failed / 640 passed / 1 skipped / 19 errors - the same 18 failures and 19 errors as
     before this step (+40 passing). The four knowledge-adjacent failures (two
     TestEngineTaskAgnostic string tests, test_mock_run_produces_knowledge_metrics,
     test_benchmark_cards_sha256_unchanged) were re-run at HEAD in the same worktree and fail there
     too, so none of them came from this step. The last one is a FileNotFoundError: the HDD card
     file is not present in this working tree at all.
  3. Twenty-two mutations against knowledge_check.py, one at a time, all killed. Two driver bugs are
     worth recording because each produced a wrong verdict, not an error:
       - stale bytecode: the first pass reported "own-category-check-dropped killed by
         test_an_unknown_evidence_class_is_rejected", which is impossible. Applying that mutation by
         hand gave 40 passed - a SURVIVED. Cause: Python reuses a .pyc when the source keeps the same
         size and mtime second, and my mutations restore equal-length-ish files within one second.
         Fixed with PYTHONDONTWRITEBYTECODE=1, clearing the package __pycache__ before the pass, and
         appending a unique marker comment so every mutated file differs in size from pristine.
         Lesson: a mutation harness must defeat its own cache or it manufactures green rules.
       - marker leak: the restore path wrote the marker too, so the target kept
         "# mutation marker pristine". The driver's byte-compare caught it on the next line; file
         repaired and md5 confirmed back at 3a9d40fb.
     One anchor matched twice (if not sources_path.exists(): appears in both load_sources and
     validate_pack), so that mutation silently did nothing; re-anchored with its message line and
     killed by test_a_missing_sources_file_is_rejected.
  4. What the impossible verdict then taught: the category check inside _validate_namespace is
     unreachable - load_cards already rejects a category outside VALID_CATEGORIES and validate_pack
     returns at the first loader error. Dead code cannot be tested, so it was deleted rather than
     given a fake test. Same for the FE*/M*/T* id pattern I first wrote: an id required to start with
     SM- can never match it, so the constant went too.
  5. Two of my own test expectations were wrong before any code was blamed:
       - test_the_readme_says_the_evaluator_is_still_missing asserted the English word "not" inside a
         Chinese document. Now it requires "evaluator" plus a negation in either language
         (\bnot\b|没有|尚未|还不), which is the claim I actually meant.
       - the renamed-HDD-pack test matched tokens as substrings, so "headline" was reported as the
         SMART attribute "head". Both the test and the validator now match word-bounded tokens
         (HDD_TOKEN_PATTERN), and the real pack passes.
Design points worth reviewing:
  - The loader deliberately accepts an empty risk, any evidence label and a dangling source id; every
    one of those gaps is a rule in knowledge_check.py, each pinned by a test that breaks exactly that
    rule. This is why the negative tests build packs in tmp_path instead of editing the real files.
  - Foreign keys go both ways. A card citing a source that does not exist is one error class; a
    source that no card cites is another, because the second means somebody read something and the
    pack kept no conclusion from it.
  - load_pack returns no cards when the pack is unsound. A run must not be steered by the subset of
    claims that happened to pass validation; validation failure is silent-only-if-empty.
  - Evidence classes are the honesty mechanism: official / paper / benchmark / user_run / expert /
    llm_hypothesis. Only the first four are used; nothing in this pack is a guess dressed as a
    citation, and no card claims a measured score on this dataset because no evaluator exists yet.
  - Tags are the retrieval interface, so the vocabulary is engineering verbs and column names
    (temporal, window, burst, parity, dq, censoring), never author shorthand. Two tests bind this:
    SmartMem keywords must return SM- cards, and HDD keywords must return nothing from this pack
    (compute_tag_match_score == 0 for smart/reallocated/sectors/power_on_hours/spin).
Boundaries kept while writing the pack:
  - sources.yaml lists only documents fetched on 2026-10-03, each with how it was read (github_api,
    arxiv_api, web_fetch) and a date. Nothing is quoted from memory, and the closed leaderboard is
    recorded as a reason why no absolute number can be calibrated - not as a target.
  - The user's prior attempt enters as one anonymous local record (evidence_class: local,
    record: docs/runs/smartmem-existing-attempt-analysis.md, author anonymous-run-1). No private path,
    no serial number; the privacy scan exists to keep it that way, and it is a rule with a test.
  - Two cards exist purely to forbid a comparison (SM-PF-001 baseline labelling is not copyable,
    SM-EV-002 a protocol change breaks comparability). Old numbers stay history, not evidence.
Interface deviation from the section 8.2 draft, recorded per 16.4:
  - The plan names four pack files; this step adds benchmark/smartmem/knowledge_check.py next to them
    (a pack validator is required by the TODO, and a module has to be importable, so it cannot live
    inside knowledge/ where a directory is a data path).
  - 23 cards against 8.3's fifteen topics: some cards cover two topics, and the count is explicitly
    not the acceptance criterion (8.2 says so), which is why the tests check provenance and refusals
    instead of length.
  - knowledge.dir is relative to task_dir per engine._get_knowledge_dir; the test asserts only
    "not absolute" so a later path change cannot quietly turn it into a machine-specific location.
Known gap carried forward:
  - No expert has contributed yet, so evidence: expert is legal but unused, and the eight open
    questions in expert.md section 5 are still 侯辰风's to answer (time-zone convention, real
    outcome_observed_until, directory and ticket filenames, filename-to-unit rule, trusted static
    source of serial_number_type for healthy units, official scoring and duplicate alarms,
    error_type domain, pyarrow in requirements, chunk size).
  - The pack is injected but never *scored*: retrieval quality (does a card actually improve a
    candidate?) needs the evaluator, so no card is marked verified on this dataset. V1-06 part 2d
    (external sort) still precedes the acceptance run.
Commit: this step
Next step and required user input: V1-06 part 2d then V1-09 (skill fe-event-data-preparation). The
  knowledge half of the phase is delivered; what it cannot do is stated in the pack README rather than
  discovered by the reviewer. Still needs from 侯辰风: the eight items above.
```

## V1-09 可复用 Skill fe-event-data-preparation：文档要能被测试钉住

```text
Step: V1-09. skill/fe-event-data-preparation/ becomes the phase's second delivered artefact - the
  reusable procedure for preparing samples from an irregular event stream, written for the next AI
  rather than for this dataset. It is the first step whose product is prose, so the tests are written
  as drift detectors: a renamed column, a dropped CLI flag or a deleted checklist item has to fail a
  test, otherwise the suite is decorating the documents instead of guarding them.
Input contract/version: SMARTMEM_PHASE1_TODO V1-09; IMPL_PLAN section 9 (14 required topics, plus the
  two prohibitions - 不得声称自动下载受许可限制的数据, 若引用脚本必须在仓库内并由测试覆盖) and the
  matching rows of section 10. Generic modules under src/faultevolve/data/ were not touched, because
  a skill describes them; it must not become the place their vocabulary lives.
Files changed:
  skill/fe-event-data-preparation/SKILL.md (new, 206 lines, 16 sections)
  skill/fe-event-data-preparation/references/canonical-event-contract.md (new, 138 lines, 9 sections)
  skill/fe-event-data-preparation/references/leakage-checklist.md (new, 54 lines, 23 checks in 4 groups)
  tests/test_smartmem_skill.py (new, 261 lines, 17 test functions -> 24 collected cases)
  README.md (one skill-index table row + one line in the Skills 路径列表 block)
  benchmark/smartmem/README.md (links the skill; states plainly that evaluator.py / init.py /
    problem.md / prompt.md are still missing, so fe doctor --task-dir benchmark/smartmem passes no
    as a whole)
Tests/commands and observed results:
  1. Red reproduced without touching this working tree: `git worktree add ../fe-v109-red HEAD`
     (detached at ade00a4, removed after the run), new test file copied in, run there
       -> 23 failed / 1 passed.
     The single green at HEAD is test_the_stub_tests_no_longer_expect_a_prepare_stub, a migration
     check for work V1-07 already landed. Its passing before this step exists is the point of the
     check, not a hole: the stub's NotImplementedError expectation is gone from
     tests/test_dataset_stubs.py and this test would fail if it came back.
  2. Green: 24 passed in 0.6 s.
     Suite: 18 failed / 664 passed / 1 skipped / 19 errors in 52.42 s - the same 18 pre-existing
     failures and 19 collection errors (missing fastapi, missing resource, absent HDD/backblaze
     trees) as before this step, with +24 passing. Recording the flag: the suite has to be run with
     --continue-on-collection-errors; without it pytest reports "Interrupted: 19 errors during
     collection" and runs nothing, which looks like a broken repo rather than a missing optional
     dependency.
  3. Twenty-three mutations against the three documents and the root README, one at a time, each
     restored byte-for-byte (the driver byte-compares after every run):
       - contract: a drop reason removed, cold_audit removed, writer.lock removed, the four-stage
         pipeline reordered -> 4 killed.
       - skill: a documented flag renamed to a typo, a referenced test path moved, a domain word
         (DIMM) added to prose, the dataset named in prose, a key-shaped string
         (DASHSCOPE_API_KEY=sk-...) added, a server path (/home/worker/raw) added, a serial-shaped
         number added, <OUT_DIR> replaced with a real path, an exit-code meaning blurred to 其他,
         the download prohibition reworded away, the checklist pointer removed, a required section
         renamed, the frontmatter name desynced from the directory -> 13 killed.
       - checklist: censoring item deleted, checks converted to prose -> round 1 survivors, re-cut in
         round 2 (vocabulary removed everywhere; row deleted) -> killed.
       - README: index row deleted -> round 1 SURVIVED, see 4b.
     Round 1 ended 18 / 20 killed. Both survivors were worth more than the eighteen kills.
  4a. First survivor was a mutation defect, not a test defect: deleting the censoring checklist line
     left the vocabulary (删失 / 随访) intact in two other items, so the doc still said the thing.
     Re-mutated as a vocabulary sweep across the file and it died - which confirms the test checks
     concepts, not line positions.
  4b. Second survivor was a real test defect, and the nastiest class: test_the_root_readme_indexes…
     asserted that a line containing "fe-event-data-preparation" exists. The README carries that
     string twice - the index table and the Skills 路径列表 block - so deleting the table row left
     the test green while the skill was unfindable in the human-facing index. Rewritten to require
     exactly one markdown row, a link that resolves to a file, and then (after a third mutation
     emptied the description cell and survived) two non-empty cells. Verified by hand: emptied cell
     -> 1 failed / 23 passed; README restored byte-identical.
  5. A drafting bug the tests did not have to catch, but which would have shipped a thinner document:
     my first inventory of the CLI's flags was `grep add_argument` line-wise and found 20 of the real
     24. --units-per-partition, --lead-minutes, --horizon-days and --sample-every-minutes are built
     inside a loop, so they never appear on an add_argument line. The contract table was corrected
     against a whole-file regex over quoted flags - the same source the test uses. Note the direction
     of the risk: the suite asserts documented flags ⊆ accepted flags, so an omitted flag passes.
     Omission is policed by review, not by CI (see Known gap).
  6. Checkout portability, because the documents were written with LF while this machine runs
     core.autocrlf=true: `git worktree add ../fe-v109-crlf 7d84559` produces the CRLF copy a Windows
     teammate gets (SKILL.md 206/206 lines CRLF) and the suite is green there - 24 skill + 40
     knowledge + 12 stub tests, 76 passed. The doc tests therefore do not depend on which line ending
     the reader happens to have. Worktree removed afterwards; nothing was pushed.
Design points worth reviewing:
  - The skill is domain-free by construction, and the guard is the same regex the generic layer uses
    (section 5.1's list verbatim: DIMM / mcelog / ECC / UE / bankid / SmartMem / smartmem). Inventing
    extra banned words would police the skill more strictly than the code it describes, so the test
    borrows the existing rule instead of a new one. Repository paths are stripped before the check:
    naming benchmark/smartmem/prepare_data.py is a fact, not vocabulary leakage.
  - Every machine-verifiable claim in the documents is generated from code: the contract's identifier
    lists come from CanonicalEventSchema / EventWindowConfig __dataclass_fields__, ANCHOR_STRATEGIES,
    OUTPUT_COLUMNS, DROP_REASONS, SCORED_SPLITS + NON_SCORED_KEYS, io.FORMATS and the manifest's
    MANIFEST_NAME / LOCK_NAME / PARTITIONS_DIR. Eight parametrized cases, one per group. A rename in
    the generic layer turns a doc test red rather than leaving a skill that describes a format nobody
    produces any more.
  - Commands have to be simultaneously runnable and anonymous, which is why both are tested: every
    path inside a bash block must exist in the repo, the block must use placeholders
    (<RAW_DIR>, <OUT_DIR>) plus an env var, and no credential shape, windows path, /home path or
    nine-digit number may appear. The first draft exported $EVENT_DATA_ROOT and then never consumed
    it, so the test requires the variable to appear in a command, not only in an export.
  - The skill states what this phase did not build (no evaluator, no score on this dataset, unconfirmed
    time boundaries, no automatic download of licensed data). A skill that reads as complete is worse
    than one that reads as sold.
Interface deviation from the section 9 draft, recorded per 16.4:
  - 16 sections against 9's 14 topics: 何时使用 opens the document and the copy-paste command block
    sits after the topics, so neither is numbered in the plan's list; 本阶段还没有建成的东西 is a
    deliberate fourth honesty section. All 14 required topics are matched by pattern, and a mutation
    that renames one section proves the match is not decorative.
  - Two reference documents instead of one inline appendix. Topics 5-7 (canonical fields, anchor and
    window arithmetic, split + embargo) are code-shaped facts an author must not paraphrase, so they
    became a contract file bound to the dataclasses; topic 10 (leakage) is an operator procedure that
    has to be tickable, so it became its own checklist with a test that it is a list of checks and
    not prose.
  - The plan asks that any referenced script live in the repo and be covered by tests. The only script
    the skill tells a reader to run is benchmark/smartmem/prepare_data.py, which V1-07 shipped with
    25 tests; the skill's own tests would fail today if that path moved.
Known gap carried forward:
  - Coverage is one-directional. Docs ⊆ code is enforced; code ⊆ docs is not, and neither is prose
    quality, ordering or whether a reader can actually follow the steps. Closing the omission half
    means reading argparse's real parser (not a regex over its source) and asserting the table lists
    every flag it registers.
  - Nothing here demonstrates that the skill helps an agent. Usefulness is only measurable against
    the evaluator, which does not exist yet, so this milestone's claim is drift resistance plus
    reproducibility, and the skill says so itself.
  - 23 leak checks is a list, not a proof. Two of its rows are provisional by design (official hit
    window, duplicate alarms) and still wait on 侯辰风's answers.
Commit: this step
Next step and required user input: V1-06 part 2d (external time-ordered sort + a disk-space estimate
  from shutil.disk_usage), then V1-10's real small-sample acceptance run, which needs the confirmed
  time-zone and follow-up boundaries from 侯辰风 - the eight items in knowledge/expert.md section 5.
  Both halves of the knowledge phase are now delivered as artefacts an agent reads; what neither can
  do is stated inside them rather than discovered by a reviewer.
```


## V1-06 (part 2d) 外排序：把乱序单元文件排成时间序，但不把它读进内存

```text
Step: V1-06 part 2d. src/faultevolve/data/external_sort.py turns one out-of-order event file into a
  time-ordered one with a bounded split-merge, and reports the workspace space it needs before the
  first byte is written. The reason this step exists at all is 2a's own refusal: iter_event_windows
  rejects a file whose chunks run backwards, which is correct but is a dead end for a real unit file,
  because those arrive unordered and 40-130 GB cannot be sorted in memory. So the refusal had to come
  with a recovery path, otherwise the only legal response to a real file was "give up".
Input contract/version: SMARTMEM_PHASE1_TODO V1-06 part 2d and IMPL_PLAN's rules for it - input order
  is not trusted, the sort is stable, concat-all is forbidden, a multi-hour run must be resumable, and
  a space failure must name the space it wanted. SORT_VERSION = esort-v1. Only generic modules were
  touched; the sort knows a time column, not a device.
Files changed:
  src/faultevolve/data/external_sort.py (new, 549 lines)
  src/faultevolve/data/__init__.py (exports the 12 public sort names)
  tests/test_external_sort.py (new, 619 lines, 30 test functions -> 31 collected cases)
  skill/fe-event-data-preparation/SKILL.md (分块 section gains the out-of-order -> sort step and the
    workspace rules; 本阶段还没有建成的东西 gains "sorting is library-level only")
  skill/fe-event-data-preparation/references/canonical-event-contract.md (new section 8
    外排序与工作区空间; the old 8 and 9 shift to 9 and 10)
  skill/fe-event-data-preparation/references/leakage-checklist.md (two new checks: sort the
    tz-aware instant, never the raw string; and an unordered input must be refused or sorted into a
    separate, digest-recorded artefact)
  tests/test_smartmem_skill.py (two more contract token groups, sort names and sort fields, built
    from the module's constants and the two dataclasses -> 26 collected cases)
Tests/commands and observed results:
  1. Red, reproduced honestly this time: a worktree at HEAD is NOT a red harness for library code,
     because the venv installs the package from the main tree in editable mode, so the copied test
     file imported the real module and reported 31 passed. The module was therefore moved out of the
     main tree and back (md5 79a972fd... verified identical after the restore):
       -> ModuleNotFoundError: No module named 'faultevolve.data.external_sort', collection ERROR for
          both tests/test_external_sort.py and tests/test_smartmem_skill.py.
  2. Green: 31 passed for the sort, 26 for the skill documents, 57 together in 3.5 s.
  3. Mutation pass 1, 30 rules: 24 killed, 6 survivors - merge-reads-a-whole-run-file,
     merge-buffer-ignores-the-bound, estimate-ignores-runs-and-passes,
     failed-sort-leaves-its-temp-files, space-error-loses-its-numbers, and
     split-sort-loses-the-sequence-key.
  4. Mutation pass 2, 8 re-checks against the strengthened tests: the three real gaps were closed by
     tests that count rows (a chunk spy, a written-block spy, and a guard that fails on any
     unbounded read_csv), and by deleting code the tests could not distinguish. The estimate
     survivor was a tautology in my own test - it compared the estimate to a constant written in the
     test, so any COPIES_AT_PEAK matched - and the message survivor replaced one number while two
     others stayed, which the test never asked about.
  5. Mutation pass 3, 7 rules: merge-buffer-ignores-the-bound, merge-reads-a-whole-run-file,
     estimate-ignores-runs-and-passes, split-sort-is-not-stable and take-ignores-the-limit died;
     two entries survived as *bad mutations of mine* rather than gaps - failed-sort-leaves-the-runs-behind
     kept the original _discard call below the inserted line, so it removed nothing. Re-anchored and
     re-run (4 rules): all killed, including space-error-drops-the-free-figure, and the module came
     back byte-identical (restored byte-exact: True, bad anchors: none).
  6. Full suite after the step: 18 failed, 697 passed, 1 skipped, 19 errors in 64 s - the same
     18 failed / 19 errors as the recorded baseline (pre-existing hdd_mvp and webapi collection
     failures, no fastapi in this venv), and 697 = 695 plus this step's two new contract token cases.
  7. The round-trip that ties 2d to 2a is asserted, not argued: a file shuffled and then block-reversed
     is refused by iter_event_windows (240 rows at chunk_rows=30), and the same file's sorted output is
     accepted by it.
Design points worth reviewing:
  - The sort key is two internal columns, not one: the instant as nanoseconds, and the row's global
    position in the prepared stream. Nanoseconds because a string time is not an order - offsets,
    precision and separators would make the "sorted" file still unordered, and the window arithmetic
    would be wrong by a silently shuffled history. The sequence column is what makes the merge
    reproduce a *stable* whole-file sort across run boundaries, and it is checked by comparing against
    pandas' own stable sort on rows that all share timestamps.
  - Boundedness is measured in rows at three places (read frames, merge blocks, written blocks), which
    is a falsifiable claim; a tracemalloc ratio would have been a number that changes with the machine.
    The multi-pass test is the one that can see the merge block bound, because a block only grows past
    the bound when a group has one cursor left and therefore no next key to stop at - that is exactly
    why the mutation survived until the spies were applied there.
  - MAX_OPEN_RUNS = 32 with successive merge passes is the difference between a demo and a real file:
    without the cap the merge opens one reader per run, which for a 130 GB file is thousands of open
    files. Two bugs found this, both real: intermediate pass files must keep the helper columns or the
    next pass dies on a KeyError, and their names must be unique - pass-{index}.csv collided, two
    cursors read one file, their keys tied, take() returned zero rows and the merge looped forever.
    That hang ran over ten minutes before being stopped, and it is the reason a suite with no timeout
    cannot be trusted to notice a non-terminating merge.
  - Space is a projection made before writing: input size x COPIES_AT_PEAK (the runs, the largest
    intermediate pass and the merged output can all be on the disk together) x a 1.1 headroom, with
    feather converted to text volume. The failure message carries needed, free and shortfall and no
    path, because a file name may itself be a unit identifier - asserted by scanning for both slashes.
  - The reuse rule is three facts, not a timestamp: config_hash, the input's sha256 and the output's
    sha256. A missing or tampered output digest is refused rather than trusted, chunk_rows is part of
    the config so drift raises ConfigChangedError (exit 2), and the runs directory is deleted as it is
    consumed so a finished sort leaves one output plus one checkpoint.
  - Refusals are placed before any write, because a partial workspace is worse than a refusal: helper
    columns already in the input (the sort would silently reorder the caller's own data), an occupied
    runtime directory, the input living inside the runtime directory, a timezone-naive time column.
  - V1-08's lesson applied twice more: the dead merged.unlink / sidecar.unlink lines in the failure
    handler and the redundant sequence key inside the split sort were deleted, not defended, once no
    mutation could reach them. Code a test cannot see is either a bug or a comment.
Interface deviation from the plan, recorded per 16.4:
  - The plan asks for a sort by (unit, time). This sorts one file by time and takes the unit from the
    file, which is the layout 2c already established (one file per unit). It is not a shortcut: the
    generic layer must not learn a unit column, so a multi-unit file would need a key this module
    deliberately does not have. If a real package arrives as one multi-unit file, the key belongs in
    the domain adapter, not here.
  - 2d is library-level only. The task CLI still reads whole files, so the "空间不足" exit-1 path has
    no flag yet; wiring chunked read + sort into prepare_data.py is the next step, and SKILL.md now
    states that limit instead of implying the capability.
Known gap carried forward:
  - The bound is in rows, and row *width* is not bounded. One pathological 10 MB text row still lands
    in memory; fixture data does not contain one and no test pretends otherwise.
  - The estimate scales with the input's size only. A file whose columns inflate more than 1.1x going
    from feather to text would still be refused late - by the disk, not by the check.
  - There is no lock: two concurrent sorts into the same workspace are stopped only by the entry
    check that the directory is not already occupied. write_partitions has writer_lock and this module
    deliberately does not share it, because a sort workspace is not a partition set.
  - Nothing here measures wall-clock, and nothing exercises a file that does not fit in RAM. The claim
    "this is what makes a real package possible" is only shown by V1-10's run on real data.
Commit: this step
Next step and required user input: V1-06's CLI half - pass the chunked reader and this sort through
  benchmark/smartmem/prepare_data.py, including the space-shortage exit-1 case - then V1-10's real
  small-sample acceptance, which still needs the time-zone and follow-up boundaries from 侯辰风
  (knowledge/expert.md section 5's eight open items). Nothing was pushed; the branch stays local.
```

## V1-06 (part 2e) 把外排序接到 prepare CLI：--sort-inputs 与"空间不足"退 1

```text
Step
  1. 红：先在 tests/test_smartmem_prepare_cli.py 写 --sort-inputs 那一段（25 条到 39 条，+14），
     观察到的红是 "8 failed, 27 passed"，失败原因就是 CLI 不认识 --sort-dir / --sort-inputs。
  2. 接线：Options 多两个字段、_build_parser 多两个参数、main 多一次模式分派，新函数
     _sort_space / _require_sort_dir / _sort_units / _write_layout / _sort_run，外加把 --out-dir
     从 argparse 的 required 挪进 _require_out_dir（argparse 的用法错误退 2，而这个位置在本 CLI
     已经归"配置变了"，所以缺参数必须自己报退 1）。prepare_data.py 895 行到 1078 行。
  3. 顺带修 2d 的一处：崩溃留下的 sorted.csv.tmp 不再被当成"别人占着目录"
     （external_sort.py 549 到 556 行，test_external_sort.py 30 到 32 条）。原子写的临时文件是
     按目标名命名的，拒绝它就等于把一次跑了两小时的排序变成非有人拿着删除清单不可恢复。
  4. 变异证明：28 个变异、28 杀、0 个锚点失配。驱动只临时替换 prepare_data.py，跑完按 md5 还原。
  5. 全量回归：18 failed / 713 passed / 1 skipped / 19 errors，失败集合与基线逐条相同
     （HDD 数据缺失 + fastapi 未装），通过数从 697 涨到 713。

新模式 --sort-inputs 的输入契约
  - 一个单元一个工作区：<sort-dir>/<queue>/<单元化名>/{sorted.csv, sort_manifest.json}；
  - layout.csv 是这一步留给下一步的索引：queue / unit / workspace / rows / runs / reused /
    source_bytes。workspace 是相对 --sort-dir 的相对路径，整张表既不出现单元原标识也不出现绝对路径；
  - --dry-run 只报 needed_bytes / free_bytes / shortfall_bytes 并带 written=False，一个字节都不落；
  - 三条拒绝：缺 --sort-dir、--sort-dir 落在 --raw-dir 之内、与 --profile-only 同时给；
  - 单元在这棵树里出现两次仍然先拒（和样本模式同一条规则）：layout 按 unit 索引，
    重复会留成两行下游 join 不上的记录。

观测到的结果
  1) 三条拒绝各退 1，消息各说各的理由，不是同一句 usage dump；
  2) 空间不足退 1 之前一个工作区都不存在，消息里三个字节数都在；
  3) 二次运行每个工作区都 reused，sorted.csv 字节不变，payload 的 reused 等于单元数；
  4) SortError 走"类型名: 消息"那一行，没有 traceback；
  5) 排序产物的 serial_number 列仍是声明的那个单元——目录名只剩化名，这是它唯一的自证。

被证伪的两条（这两条比通过更值得记）
  - "输入乱序"这条断言一开始是假绿：read_smartmem_file 会把整个文件排好序再返回，所以用它问
    "这个文件乱不乱"永远答"不乱"。改成直接 pd.read_csv 看盘上顺序（disk_times），先断言 fixture
    确实带着 DISK_ROW_ORDER 那份乱序，再断言排完的那份有序。顺带把这一步排序存在的理由说清楚了：
    超大文件不能整文件读，只能走分块路径，而分块路径没有全局序。
  - _sort_units 里的 prepare 闭包原本写成 def prepare(chunk, *, declared=unit)。"改成运行期再取
    unit"这个变异杀不掉——闭包在同一次迭代内就被消费完，两种写法等价。按 V1-08 立的规矩（没有
    变异能区分的代码要么删要么简化），去掉默认参；换一条真能区分的变异："声明单元改成 whatever"
    必须失败，它由上面第 5 条结果杀掉。

已知偏离，按需求 16.4 记录
  - 排序树不写 manifest.json，也不吃 --resume：它的续跑判定在每个工作区的 sort_manifest.json 里。
    一份运行清单管两种产物，会让人误以为换 --sort-dir 也算换实验。
  - --out-dir 由"必填"变成"除 --sort-inputs 之外必填"。

没建成的部分（别当成已支持）
  - --sort-inputs 只生产、不消费：样本模式仍按整文件读，所以"吃得下超内存的数据"这句现在只对
    排序这一步成立。把 sorted.csv / layout.csv 变成样本模式的输入是这一步的下一半。
  - 哪几个文件该排仍需人判断（分块路径遇到乱序会报错，报错的那个文件就是要排的那个），
    没有自动挑选。
  - layout.csv 没记输入指纹：排完之后原始文件被改动，这一步不会发现。
  - 聚合空间判定过关不等于每个文件都过关——单文件那套检查仍然生效，只是顺序上晚于聚合。

提交：本步
下一步：V1-10 真实小样本验收，仍等侯辰风确认 knowledge/expert.md 第 5 节那 8 项。
  分支 feat/smartmem-data-knowledge 推远端给队长看；基线仍是 a366c92，origin/main 之后的 77 个
  提交与本分支的 41 个文件零重叠，所以不 rebase、不开 PR。
```

## V1-06 (part 2f) 让样本模式吃排序树：--from-sorted 与两条摘要

```text
Step
  1. 红：CLI 侧 14 条 + 分块等价侧 3 条先写先红，红的形态是 "_ArgsError: unrecognized arguments:
     --from-sorted"，没有一条是空过（CLI 文件 39 条涨到 53 条）。
  2. 接线：Options 多一个 from_sorted、main 多一次"先验树再读"的分派、_event_reader 把"怎么把一
     个单元文件变成行"收到一处（raw 与 sorted 两条路共用同一个 reader 形参），新增
     _require_sorted_entry / _sorted_layout / _verified_workspace / _sorted_event_files 四个函数，
     领域侧新增 read_sorted_smartmem_file。prepare_data.py 1078 行到 1190 行。
  3. 等价性主张分两层锁：库层 read_sorted_smartmem_file(...).equals(整读原始文件)，CLI 层两次运行
     的分区文件逐字节相同、且 config_hash 相同。
  4. 变异：对消费路径一共造 11 个变异，杀 10 个，1 个是设计上就观测不到（见下）。

为什么"找回工作区"不能靠路径
  排序树里一个单元一个工作区，但工作区目录名是化名——路径里不许出现单元原标识是 V1-07 立的规则。
  所以找回来的桥只有 layout.csv：键是 (queue, 化名)，值是相对路径；数据自己带 serial_number 列，
  行落在哪一格由内容说，不由目录名说。

"这棵树还能信"被写成四条可证伪的检查，而不是一段说明
  - layout.csv 缺 → 退 1，并点名只有 --sort-inputs 会写它；
  - 列名不等于本步写的那一套 → 退 1（换了别的契约的索引不算索引）；
  - 同一 (queue, unit) 出现两次 → 退 1，因为运行不知道该读哪个工作区；
  - 每个工作区：sorted.csv 在不在、sort_manifest.json 在不在、里面两个摘要记没记、
    input_sha256 是否仍等于当前原始文件、output_sha256 是否仍等于盘上的合并文件。
  前一轮 dev log 里"layout.csv 没记输入指纹"那条缺口，靠 input_sha256 这一条补上：排完之后原始
  文件被改动，消费运行会拒绝，而不是拿一份旧排序当输入。所有拒绝文案只出现化名。

一处补齐：跨块重复
  分块路径只能看见块内的重复，所以一对被切进两个块的重复合对会留在 sorted.csv 里。
  read_sorted_smartmem_file 对整表重做第 7 节的规范化与 drop_exact，因此"消费排序树"与"整读原始
  文件"行集相同。这条断言不是空转：chunk_rows=1 时合并文件确实是 7 行、整读是 6 行、reader 回到
  6 行；如果去掉 reader 里的规范化，测试当场就红。

被证伪的三条
  - "capsys 里读不到 JSON"一开始被我当成载荷坏了，实际是 sorted_tree() 把 "sorted 9 unit files…"
    打进了同一个 stdout 缓冲，JSON 前面垫着一行人话。改成建树之后显式 readouterr() 排空。
  - --max-files 3 让原始树那趟先退 1（"empty_split=2"），我一度以为是消费路径的错。实测 3..9：
    ≤6 都过不了审计，7 起才过——是切片太小、train 窗里没有正样本。测试最终取 8（仍小于 layout
    的 9 行，"窄列表落在宽树上"这条覆盖检查照样有效）。
  - 两次运行共用一个 --out-dir 会撞上"already records 2 partition(s); pass --resume"。给两次各
    一个目录名，不是给它们加 --resume：这条比较要证的正是"同配置两次独立运行"。

一个观测不到的变异（诚实记着）
  把消费分支的 reader 换成"照样读原始文件"，64 条全绿——两条路在同一批字节上必须产出同样的分区
  字节（那本来就是 2f 的主张），所以差异只在内存与 IO 形态，不在数据。这一条由 events 标签
  （raw-files / sorted-tree）与上面那五条摘要拒绝共同守边：能测的是"声明的来源"和"来源不可信时拒
  读"，"到底有没有走那条路"只能由 IO 断言测，本 CLI 没有那种断言。
  同理，read_sorted_smartmem_file 里显式写的 duplicate_policy="drop_exact" 与 event_schema 的默认值
  等价，删掉不会有任何测试变红。它留着是因为这一行的读法是整个消费路径的口径，不该跟着默认值走。

已知偏离，按需求 16.4 记录
  - --from-sorted 不进 config hash：一棵摘要全对的排序树只是到达同一批字节的另一条路，两次运行该
    记同一个配置。payload 的 events 字段把来源说出来，而不是把它编进配置身份。
  - --from-sorted 与 --sort-inputs、--profile-only 互斥；它不改写树（一次消费运行前后整棵树逐字节
    相同，由测试锁住）。

提交：本步与下一步的 --epoch-unit 一起
下一步：真实小切片端到端（V1-10），见下一节。
```

## V1-10 (前置) 真实包读得动了：--epoch-unit 与 12 个真实单元的落盘

```text
为什么先补这一步
  库层三个入口（read_smartmem_file / read_tickets / prepare_smartmem_chunk）本来就收 epoch_unit，
  CLI 偏偏没有对应参数。真实包的两个时间列是裸整数，于是任何一条真实命令都在第一口读上退 1：
  缺的不是数据，是把"这串数字按秒读"说出来的一条口子。

Step
  1. 红：9 条新测试先红（"unrecognized arguments: --epoch-unit"）；其中两条是对今天行为的钉子——
     裸整数不给单位必须退 1 且点名是 failure_time（样本模式）还是 log_time（dry-run 先读事件），
     这两条今天就是绿的，写它们是为了别以后退成了"泛指时间错误"。
  2. 接线：Options 多 epoch_unit、parser 多 --epoch-unit（choices 就是库层的 EPOCH_UNITS）、
     _read_options 一处映射、config 载荷多一个键，其余是把同一个值送到五个调用点。
  3. 变异：8 个变异全杀，包括"config 载荷不记它"（退 2 那条杀）与"parser 不收 choices"
     （invalid choice 那条杀）。

口径实测（这些数字来自只读扫描与一次 12 单元的落盘，不是文档转述）
  - 本机资源：物理内存 31.4 GB、逻辑核 20、C 盘剩余 109 GB；pyarrow 25.0.1 已装，feather 可读。
  - 本地镜像规模：raw_tmp/type_A 33 GB / 56,403 个文件，raw_tmp/type_B 703 MB / 5,821 个，
    features 7.9 GB。合计 41 GB 级，比内存大 ⇒ "整读一次"在这台机器上不成立，V1-06 那条分块 +
    外排序的链子不是为测试造的，是真需要。
  - 时间列：feather 里 LogTime 是 int64 秒；裸整数是绝对时刻，所以 --timezone 对这一列只决定显示，
     不移动值（epoch 分支先转成 tz-aware UTC，再走 tz_convert）。naive 文本时间相反，时区真的改值。
  - 告警表：836 行 / 836 个不同 SN，A 768 B 68；alarm_time 全是纯数字秒，无缺失、无空值；
    最早 2024-01-01T02:57:30Z，最晚 2024-05-31T15:47:45Z；没有重复 ticket 行；
    每个 ticket 的 SN 都在事件树里有文件（缺失 0 个）。
  - 同一 DIMM 多次故障：这份数据里不可触发——ticket 按 SN 唯一。所以"重置身份"这条规则在本地镜像
    上没有可执行样本，只能作为缺口保留，不能声称已支持。
  - A/B 来源：两个队列目录零重叠（没有任何 SN 同时出现在两边），836 个 ticket 的 sn_type 与它所在
    目录 836/836 一致、0 冲突、0 无法判定 ⇒ 目录是可信静态来源，用它不泄露标签；ticket 列退化为
    校验位。
  - 事件表里没有承载序列号的列（24 列扫下来只有 error_type_full_name 像"id"列）——文件名是唯一
    的单元来源。需求文档那条"不许假设去扩展名就是 SN"由此不是形式要求：分块路径用
    unit_from_filename + 声明单元喂 normalize，声明与内容不一致就在排序阶段当场报错。
  - 事件类型取值：只有 CE.READ / CE.SCRUB，UE 不在事件流里（它来自 ticket）。
    DEFAULT_ERROR_TYPES 写的是 ("ce", "ue")，与真实域不符，切片跑必须显式
    --error-types CE.READ,CE.SCRUB,CE。
  - 乱序是真的：抽 5 个真实 SN，LogTime 单调递增的全是 False（降序次数 10 / 4 / 1 量级）。

12 单元端到端（3 条命令，全退 0）
  切片：type_A 6 个有告警 + 4 个无告警，type_B 2 个有告警；ticket 表按切片过滤后 8 行；共 1.4 MB。
  - --profile-only：12 个文件、30,720 行、时刻跨度 2023-12-31T20:44:19Z .. 2024-07-15T21:46:21Z，
    写出一个 profile 分区。
  - --dry-run：报出 suggest_split_boundaries，并明说它是按 3 个文件抽的样（span_sampled_files=3），
    与 profile 的全量跨度不同——这一步不给结论，只给候选。
  - 落样本：边界手定 start 2024-01-01 / train_until 2024-04-01 / dev_until 2024-05-01 /
    val_until 2024-06-01 / outcome_observed_until 2024-07-16（后者就是实测事件前沿），
    --units-per-partition 4 --workers 2 → 734 条样本、44 列、审计 passed=true，
    train 560 / dev 59 / val 44 / embargo 60 / outside 11，8 个有告警单元全部拿到正样本，
    三个划分里都有正例。
  切片放在两个项目之外的临时目录里做，原始数据一个字节没动。

没建成的部分（别当成已支持）
  - 734 条是"跑通了"的规模证据，不是分数。事件流里没有 UE、也没有 evaluator，任何 F1 表述在这里
    都不成立。
  - 样本表里没有 serial_number_type 这一列：A/B 现在只在目录层。写出 submission 之前需要一张
    单元→类型的静态侧表（工单表只覆盖有告警的单元，误报出去的单元拿不到类型）。
  - 真实包 train.zip 解出来的目录名与列方言仍未实测：本地这份是导出方言（CpuId / LogTime /
    Manufacturer / error_type_full_name），官方文档写的是 mcelog 方言（log_time / manufacturter），
    adapter 里 EXPORT_TO_MCELOG 能互转，但"哪一份是验收目标"要人定。
  - 随访前沿目前用的是全局最大事件时刻，逐单元各自前沿还没接线。
```

## V1-10 (前置 2) 取值域不许靠口头：--error-types 默认改成实测域，另加三条校验

```text
背景
  用户选项「改默认 + 加取值域校验」。旧默认 ("ce", "ue") 是合成 fixture 的拼写，真实事件流的拼写是
  大写带点，所以跑真实数据必须手动 --error-types 才能过；而一旦忘了改，管线不会报错——它照样写出一
  整张表，只是每个 error_type 特征都读零，唯一的痕迹是没人对比的 unexpected_error_type_count。

Step
  1. 红：tests/test_smartmem_prepare_cli.py 先写 8 条（观察到的红是 "8 failed"，全是退出码 0 撞上
     期望的 1，以及 profile 表里根本没有 error_type 行）。最终这份文件 67 条到 79 条。
  2. 库层：src/faultevolve/tasks/smartmem_data.py 新增 declared_error_types 与 error_type_counts，
     两个都进 __all__。校验函数直接调用 _slug，不重写一份拼列名的规则——校验若自带规则，它去认证的
     就是一张 history_features 从来不会产出的表。
  3. CLI：DEFAULT_ERROR_TYPES 改成实测的三种拼写；_read_options 改走 declared_error_types；
     _profile_entries 多返回一份观测域；_profile_run 里把 _require_declared_domain 放在写盘之前。
  4. 顺带的契约变化（本轮唯一一处）：_profile_entries 原来在 PartitionJob 的 build 里才执行，读取
     错误因此算分区失败（退 3）；现在它提前到写盘之前，schema 类错误按 §7 归退 1。profile 只有一个
     分区，退 3 与退 1 在它身上本无区别，而样本模式仍留在 build 里（有 EXIT_PARTIAL 的测试钉着，
     本轮没动它）。
  5. 文档三处：契约 §10 新增 --error-types 段、SKILL.md schema 探查段补一句、知识包 expert.md 第 5
     节把 8 条开放问题按「待确认 / 已定口径 / 已实测 / 本仓自定」重新标注。
  6. 变异：20 个变异体（prepare_data.py 13 个 + smartmem_data.py 7 个），20 杀 0 存活，锚点全部命中
     一次；驱动跑完按 md5 还原，两份文件字节一致。
  7. 全量回归：18 failed / 762 passed / 1 skipped / 19 errors。失败集合与基线逐条相同（HDD 数据缺失
     + fastapi 未装），通过数 744 到 762；三个受影响文件 79 + 28 + 27 条全绿。

三条校验的分工
  - 解析阶段（每种模式都过，动手之前就退 1）：一个名字都不剩时拒绝；两个名字拼成同一个 *_count 列
    时拒绝——CE.READ 与 CE_READ 都落到 ce_read_count，后一个计数会把前一个盖掉且不留痕迹。
  - profile：观测到的取值与声明的取值一起写进 profile 表（scope 为 error_type），声明了却没出现的
    名字记 0 行。「UE 只来自工单」由此变成表里的数字，不是口头约定。
  - profile：声明的域一个事件行都盖不住时退 1，消息同时点名两边，最多列 5 个观测值再补 "plus N
    more"。比较区分大小写，所以小写拼写的合成 fixture 必须自己声明 --error-types。

被证伪与被打回的写法
  - 「profile 拒绝要写在哪一步」最初写成写盘之后再检查：P10 变异把检查移到 write_partitions 之后，
    test_a_default_domain_that_matches_nothing_writes_no_partition 立刻抓到——拒绝必须发生在留下
    分区之前。
  - 测试里最初硬编码了 "CE.READ": 38 / "CE.SCRUB": 8 两个数。那是猜的。改成 reader_types()：用同一
    个读器逐文件数一边、与 profile 表比，既不用猜数，也能杀掉「只把最后一个文件计进域」的 P11。
  - 检查函数一度想在测试里再实现一遍 _slug 来构造撞列对——那等于用第二份规则去认证第一份。改成用
    history_features(feature_groups=("error_type",)) 反取列名：被拒的对与会撞列的对由 builder 自己
    说话，测试里不出现第二套拼写规则。
  - 打回过一条「声明表超过 5 个就拒绝」的想法：域宽不是错误，只是消息要截断。
  - 留下的口子：名字拼成纯标点时 _slug 兜底成 blank，规则不拒它（会写出 blank_count 一列）；零覆盖
    检查会退 1 兜住，所以它不会静默。

顺带纠正一条我自己写错的事实
  前一轮把「460 个单元文件、6 245 208 行」当成了整包口径写进注释与文档。实测目录：镜像是
  raw_tmp/type_A（56 403 个）+ raw_tmp/type_B（5 821 个）共 62 224 个 sn_<编号>.feather，约 33 GB，
  外加一份 ticket.csv（836 行，列名 sn_name / alarm_time / sn_type），镜像里没有 train/ 目录，
  features/failure_ticket.csv 与 raw_tmp/ticket.csv 是同一份工单的两份拷贝。460 文件只是我扫过的
  样本，本轮把 prepare_data.py 注释、契约 §10、expert.md 第 6 条都改成「样本口径」，并写明这个默认
  值是可被 --profile-only 当场证伪的声明，不是官方口径。

下一步
  200 个真实单元的切片端到端：--sort-inputs 产树，再用 --from-sorted 复跑同一份样本，比对分区字节
  与 config_hash；数字落进 docs/runs/ 的输入证据文件。

## V1-10 200 单元真实切片端到端：产树、两条路径各复跑一遍、逐列比对

做法
  切片放在两个项目之外的 D:/sm-slice200，原始镜像一个字节没动。按体积降序等间隔抽 200 个单元，
  其中 140 个带告警、60 个不带（纯按体积抽只能捞到 2 条工单，样本会退化成 198 个负例，所以改成
  「有工单 140 + 无工单 60」两列各自等间隔抽）：type_A 195 / type_B 5，原始 297 401 093 字节，
  最大单个 61 793 482 字节，最小 11 842 字节。选材刻意保留巨文件，就是要压外排序的最坏路径。

  四步连续跑，全部 --format feather --timezone UTC --epoch-unit s：
    1) --dry-run：files=200、partitions=50、bytes=297 397 864、free=502 037 950 464，退 0。
    2) --profile-only，**不带 --error-types**：退 0，config_hash f6611773…280ca4，
       row_count 6 281 694、unit_count 200、empty_files 0、ticket_rows 140，
       实测跨度 2023-12-31T16:00:03+00:00 ~ 2024-07-31T15:59:45+00:00，
       error_type 三行 CE.READ 6 249 429 / CE.SCRUB 31 349 / CE 916，三者相加正好等于 row_count。
       ⇒ 上一轮那条「默认值可被 --profile-only 当场证伪」的声明当场兑现了：不加参数也读得动真包。
    3) --sort-inputs：退 0，files=200、rows=6 281 694（与 profile 逐位相同）、reused=0、
       layout.csv 201 行（表头 + 200 单元），产出 1 243 436 980 字节 = 输入的 4.18 倍；
       CLI 事前估的 needed_bytes 是 1 962 826 011，比实际多估 1.58 倍（宁可多估，方向对）。
       墙钟 149 分 16 秒。
    4) 样本模式跑两遍，除事件来源外所有入参一致（--units-per-partition 4 --workers 2，同一份
       split.yaml）：raw 路径 5 分 52 秒 / 7 238 286 字节，--from-sorted 路径 6 分 12 秒 /
       7 219 062 字节，两边都退 0、50 个分区、审计 passed=true、样本 19 540 行
       （train 15 516 / dev 1 967 / val 1 264 / embargo 603 / outside 190、cold_units 0、violations
       空）、config_hash 同为 fd5a113d…74bd40。

split.yaml 是被实测改掉的，不是手写的
  上一轮手写的边界（start 2024-03-20T02:11:39、outcome 2024-07-18T20:42:06）来自 --dry-run 的
  抽样建议，而它只读了 3 个文件，落在本轮实测跨度之外。按用户定的「全局随访前沿」口径重算：
  outcome_observed_until = 实测 time_max = 2024-07-31T15:59:45+00:00，
  train_until 2024-04-30 / dev_until 2024-06-15 / val_until 2024-07-20，
  留住 val_until + 7d15m embargo ≤ 前沿这条硬约束（否则有测试直接拒）。

两条路径到底差在哪（逐列比对，不是看总和）
  两边 50 个分区按 sample_id 对齐后逐列比：19 540 行 × 45 列，**真实数值差异 0 处**。
  ~~只有 14 612 个格子是「同一个值两种写法」：FrequencyMHz 13 549、MaxSpeedMHz 997、
  retryrderrlog_marked_rate 33、parity_marked_rate 33~~ —— **这组数已在 10-04 复核中撤回**，
  见下面「V1-10 (前置 2) 复核」。真实的是：**9 612 格，只出现在 FrequencyMHz（1 015）与
  MaxSpeedMHz（8 597），两个 marked_rate 一格不差**；形态固定是 feather 路径写 4000.0（float64）、
  排序树路径写 4000（int64）。计数类、distinct 类、窗口类特征全部逐字节相同。

被打回的两次自我判断（都写下来，免得下次再信）
  - 我先说「分区字节不同 ⇒ 两条路径不一致」，还把差异按单元体积分了组，得出「35 个超过 16 384 行的
    单元全发散、46 个干净单元最大才 13 986 行」，据此猜是「raw 路径只在块内排序」。这组相关是真的，
    因果是假的：拿 NaN 语义和 dtype 归一重算后数值差异为 0，真正的机制是**整列 dtype 由分区里所有
    单元共同推断**，巨文件把某列推成 float，写法才跟着体积走。撤回。
  - 第一版比对用 astype(str) 直接比，NaN != NaN 造出 273 560 处「假差异」（整列字符串列全被
    to_numeric 压成 NaN）。结论必须写清是"数值等 + 写法等"两个判据，否则会把渲染当成数据错。

由此立下的两个待修口子（本轮没动代码）
  1) 写出样本前把 dtype 归一（频率/速率这类列固定成同一口径），否则两条路径永远做不到逐字节相等，
     「同配置同字节」这条契约就没法当验收判据。这是最便宜的一条，改完 9 612 处渲染差异应归零。
  2) ~~config_hash 不覆盖事件来源~~ —— **这条已撤回**：`_config_payload` 的文档写明 `--from-sorted`
     是有意不进哈希（"摘要仍与原始文件一致的树，只是到达同样字节的另一条路，两次跑应当记同一个
     config_hash"），而 `events` 标签本来就在 payload 与 manifest 里，来源没丢。今天实测真正推翻的是
     它的前提：两条路并没有到达同样字节，差在 9 612 格渲染。所以第 1 条不是收尾，是把这条设计不变量
     重新钉住，并补一条「同 config_hash 且同分区 sha256」的契约测试。
  3) 巨文件的归并成本：DEFAULT_CHUNK_ROWS = 16 384 没暴露成 CLI 参数，60 MB 级单元切成 30~49 块，
     49 块那个超过 MAX_OPEN_RUNS = 32 只能多走一趟中间归并。实测单趟 30 路归并 93 KB/s、
     两趟那种 192 KB/s，149 分钟里约 100 分钟是 3 个巨文件吃掉的。改进方向是攒够 N 行再落盘 +
     把 --chunk-rows 开出来，别在机械盘上按队头逐块 to_csv。

还没解释清楚的
  切片 200 个单元，样本表里只出现 195 个：5 个单元一个样本都没产。cold_units=0 说明不是「冷单元」
  规则挡掉的，最可能是事件太少或全落在窗口外，但本轮没逐单元追。留作下一条待核事实。
```

## V1-10 (前置 3) 那 5 个零样本单元追因：一条规则的代价，加一条要人定的前沿口径

怎么追的
  全程只读：raw 目录取 200 个单元名，与两条路径的样本表取并集（195 个），差集就是缺席的 5 个
  `单元#1 / 单元#2 / 单元#3 / 单元#4 / 单元#5
  （这 5 个序列号在本仓文档里一律脱敏成 单元#1-#5；原值只存在于本地切片产物，不进气泡、不进提交。）`。再对每个单元读原始行、取事件首末时刻、
  查 `sorted/layout.csv` 的行数，最后把唯一那个"本该有样本"的单元单独拷进 one-unit 目录跑 CLI，
  并直接调库函数拿删除计数 report。原始镜像没动。

结论一：5 个里有 4 个是**规则应该有的行为**
  `单元#1`（3 行）、`单元#3`（1 行）、`单元#4`（1 行）、`单元#5`（15 行）全部没有工单，
  事件落在 2024-07-29 ~ 2024-07-31，一条都不在 `val_until 2024-07-20` 之前；以它们的锚点算
  `label_window_end = 锚点 + 15min + 7d` 已经越过随访前沿，删失规则把样本判成 censored 是对的。
  ⇒ 这四条不是缺口，是"不能确认无故障就不给负样本"这条纪律在真实数据上第一次真跑到。

结论二：`单元#2` 那条暴露的是锚点量化的代价，不是数据脏
  它有 69 行事件、全部在 2024-01-28 08:08:16 ~ 08:25:46（跨度 17 分 30 秒），工单在 08:26:06，
  **最后一条事件距告警只有 20 秒**。事件策略的锚点是「每个事件向上取整到 15 分钟刻度」
  （`_ceil_to`，`make_prediction_times` 的文档写明不许向下取整，因为向下会让 10:00 的样本读到
  10:07 才发生的日志）。于是两个候选锚点 08:15 与 08:30 分别被记成 `insufficient_lead=1`
  与 `post_failure=1`，report 全文 `{empty_history:0, post_failure:1, insufficient_lead:1,
  censored:0, max_samples_dropped:0}`，样本 0 条。
  但这 69 行里有 20 行早于 `告警 − 15min = 08:11:06`，也就是说**按原始事件时刻当锚点是合法的
  正样本**，量化到刻度把它抹掉了。
  ⇒ 本轮不改这条规则：它有 `test_event_anchor_ceils_within_the_bucket_never_floors` 钉着，
  是刻意的流式真实性约束（日志到达的那一瞬不能拿来预测）。要改的是**把它记成已量化的信号损失**：
  本切片 140 个有告警单元里 1 个因此完全拿不到正样本，占 **1/140 = 0.71%**，在指标上等价于必漏。
  换官方全量后这个比例必须重测，不能外推。

结论三：更要紧的一条——今天的 split 前沿取错了口径（要人定）
  今天的 `outcome_observed_until` 按「全局随访前沿」取了**数据里最晚的观测时刻** 2024-07-31T15:59:45。
  实测：切片这 140 条工单的 `max(alarm_time)` 是 **2024-05-31 01:13:37**，事件前沿比工单覆盖晚
  **61 天**。后果量化出来是：
  - 19 540 行样本里有 **1 866 行（9.5%）锚点在工单覆盖之后，且 label 全为 0** —— 它们是被
    "确认无故障"名义下的**假负例**；
  - 按今天这条前沿：`val` 1 264 行**一个正样本都没有**（`outside` 190 行同样为 0），
    `dev` 694 正、`train` 3 872 正。⇒ 现在这把尺子在 val 上根本算不出 F1。
  - 审计照样 `passed=true`：审计只看泄漏与划分非空，**不看工单覆盖到哪天**，所以它抓不到这类错。
  机制本身没坏：删失规则一直是拿 `outcome_observed_until` 当闸门的，只要把前沿取成
  `min(事件前沿, 工单覆盖末)`，那 1 866 行会自动被判成 censored 而不再冒充负样本。
  这条与 V1-00 输入证据里「候选取 2024-05-31 当日结束」是一致的，与本轮「取最晚观测时刻」的
  实现口径冲突，所以**不擅自改**，等人定。

下一步
  1) 前沿口径定了之后重出 `split.yaml` 与两条路径的样本表，并把 val 重新落回有标签的区间。
  2) 写出样本前归一 dtype，让 raw 与 `--from-sorted` 两条路径逐字节相等（本轮实测差 9 612 格渲染）。
  3) 单元→`serial_number_type` 侧表：写 submission 之前必须有，工单只覆盖有告警的单元。

## V1-10 (前置 4) 写出前按声明口径归一渲染：两条路径第一次逐字节相等

先说清楚差的是什么
  上一轮的读数更正过一回：**9 612 格**文本不同，全部落在 `FrequencyMHz`（1 015）与
  `MaxSpeedMHz`（8 597），两个 `*_marked_rate` 一格不差（此前我写"14 612 格、4 列"是错的，
  已撤回）。数值差异 0 处 —— 也就是说这不是"两条路径算出不同的数"，是**同一个数两种写法**：
  `4000.0` 对 `4000`。
  机制追到存储层：镜像里同一个静态数值列，有些单元存成 int64、有些存成 float64 且带空洞
  （`FrequencyMHz` 在排序树路径里同时出现 `2600` 与 `2600.0`，就是这个原因）。feather 直读
  把 arrow 的 dtype 原样带出来，排序树的 `sorted.csv` 则把所有写法压成文本再用 `dtype=str` 读；
  于是"由一列里混着 numpy int64 与 float64 标量"推断出来的 dtype 随分区的单元集合而变，
  渲染就跟着变。排序树只是运输方式，不该是第二次实验 ⇒ 渲染口径必须在这一层定死。

口径
  `FEATURE_MANIFEST` 里静态列的 dtype 从 `"source"` 哨兵（等于"我不负责渲染"）换成真口径：
  `Capacity / FrequencyMHz / MaxSpeedMHz` → `int64`，文本静态列 → `string`，`_ratio` 与
  `*_marked_rate` 族 → `float64`。契约写死一句：**整数值渲染成 `4000`，不发明小数精度**。
  `"source"` 这个字面量在仓里只有定义处与 manifest 构造处两次引用，没有卡片或测试依赖它，
  所以退得掉；新增 `test_every_declared_feature_dtype_is_one_this_layer_applies` 钉住
  "声明了却没人执行的 dtype" 不许再出现。

实现
  `canonicalize_feature_types(frame, *, manifest=FEATURE_MANIFEST)`：`int64` 先 `to_numeric`，
  再校验非空格子全是整数，最后 `astype("Int64")`；`float64` 直接 `astype("float64")`；
  `string` 把纯空白归成 `None`；manifest 没点名的列原样保留（样本行本身与逐错误类型计数各有
  自己的口径）。两道拒绝都是为了**不许凭空造数**：
  - 非空格子读不成数字 ⇒ 退 1（`errors="coerce"` 自己会把 `32GB` 悄悄变成空格子，特征表少一个
    数而处处无错）；
  - 声明 int64 却真有小数 ⇒ 退 1，宁可让人改声明，也不截断日志写明的值。
  调用点唯一：`add_history_features` 返回前（`smartmem_data.py:1008`），在划分审计与分区写出
  之前 ⇒ 审计看到的字节就是写出的字节。

先红后绿
  红的时候 12 条特征测试 + 1 条新的 CLI 契约测试同时红，CLI 那条报的是
  `65536.0,2933.0,3200.0` 对 `65536,2933,3200`。为了让它当场是红的，`tests/helpers_smartmem.py`
  的 `write_fixture` 加了 `typed_statics=True`：把频率/容量按单元分别存成 float64（并在一个单元
  掺一个 NaN）与 int64，于是 `--format feather` 直读给出 `4000.0`、`--from-sorted` 给出 `4000`
  ——这正是真实切片上的症状，不是我编的题型。
  绿：`tests/test_smartmem_features.py` 42 条、8 个 SmartMem 测试文件 271 条、全量
  **18 failed / 777 passed / 19 errors**，失败与错误集合跟基线**逐条相同**（既没新增失败，也没
  把谁带绿）。另有一次并发跑出来的 17 failed / 774 复现不出来，以这条干净记录为准。

变异证明（6 条，逐条只让对应测试变红）
  M1 从数字静态列里漏掉 `MaxSpeedMHz` → KILLED
  M2 写出前不归一（`return out`）→ KILLED
  M3 去掉"必须是整数"这道拒绝 → KILLED
  M4 去掉"读数丢失"这道拒绝 → **起初 SURVIVED**：`Capacity` 是 int64 声明列，文本格子会先被
     M3 那道"不是整数"拦下，所以我那条 `32GB` 测试测不到 M4 这道守卫。补一条针对 `float64`
     列（`growth_rate` 塞 `"n/a"`）的测试——float 分支只有这一道守卫——之后 KILLED。
     这条是本轮唯一一次"我的测试以为覆盖了其实没覆盖"，值得记住：拒绝分支要按分支测，
     不能按"报的是同一列名"测。
  M5 接受一个本层不会执行的 dtype 声明 → KILLED
  M6 把归一挪到读回之后（审计之后）→ KILLED

真实切片复跑（本轮验收判据）
  两条路径各重跑一遍，配置与上一轮完全相同（`--format feather --timezone UTC --epoch-unit s
  --split-config split.yaml --units-per-partition 4 --workers 2 --min-free-gb 5 --json`），
  产物写进**新**目录 `out-raw2` / `out-sorted2`，旧目录与 149 分钟造好的排序树都没动：
  - A raw：09:09:05 → 09:14:58（5 分 53 秒），退 0，`rows=19 540`，
    划分 `train 15 516 / dev 1 967 / embargo 603 / val 1 264 / outside 190`，审计 `passed=true`
  - B `--from-sorted`：09:14:59 → 09:21:27（6 分 28 秒），退 0
  - `config_hash` 两边同为 `fd5a113d7f3c8589488e05dbe640f5423b4a22c9a61742b6aa21ac5b8f74bd40`
  - 51 个分区（50 样本 + `audit/summary`）的 **sha256 逐分区相同，0 处不同**
  - 19 540 行按 `sample_id` 对齐后**文本差异 0 格**（修前 9 612）
  - 逐列复查写出字节：所有以 `.0` 结尾的格子都来自声明 `float64` 的列
    （`growth_rate`、`minutes_since_last_event`、两个 `*_marked_rate`、`rowid_repeat_rate`、
    `top_rowid_share`、`window_fill_rate`、`window_span_minutes`），声明 `int64` 的列一格 `X.0` 都没有
  ⇒ 上一轮立的那条契约（两条路径必须同 `config_hash` **且**同分区 sha256）现在真的能当验收判据用了。

顺带挖出来的两条（都没改，先记）
  1) **渲染口径不进 `config_hash`**。`_config_payload`（`prepare_data.py:615`）列了 17 项，没有
     一项描述特征渲染策略。后果：拿旧的 out 目录续跑，已完成的分区（旧写法 `4000.0`）会被当成
     已完成跳过，新写的分区是 `4000`，两者挂在同一个 `config_hash` 下 —— 一个 out 目录里混两种
     口径而闸门毫无反应。本轮实测恰好是这条的反面证据：改前改后 `config_hash` 一字未变
     （`fd5a113d…`），所以它**看不见**这次改动。下一轮补一个 `feature_rendering` 版本进 payload，
     并配一条"旧口径目录不许续跑"的测试。
  2) manifest 顶层 `status` 只在创建时写 `"open"`，没有任何步骤把它改成完成态；跑完与跑断在顶层
     看不出来，恢复判定完全依赖逐分区 `complete` + `config_hash`。旧产物（`out-raw` / `out-sorted`）
     同样是 `"open"`，**不是本轮引入**，先记不追。

下一步
  1) 前沿口径人已定（取工单覆盖终点 `2024-05-31T01:13:37+00:00`）：重出 `split.yaml`、
     把 `coverage` 缺口进运行载荷显式暴露、两条路径再各复跑一遍。
  2) 单元→`serial_number_type` 侧表 + 进配置指纹。
  3) 本地 evaluator，让 F1 第一次可算。

## V1-10 (前置 5) 前沿口径落地：工单覆盖终点进 split，覆盖缺口进运行载荷

口径（人已拍定 2026-10-04）
  `outcome_observed_until = min(事件前沿, 工单覆盖终点)`。切片上工单覆盖终点是
  `2024-05-31T01:13:37+00:00`（140 条工单，`max(alarm_time)`），事件前沿 `2024-07-31T15:59:45`，
  所以前沿取前者。**新边界单独写成 `split-v2.yaml`，`split.yaml` 原样留着**，两次的产物目录也分开
  （`out-raw3` / `out-sorted3`），这样"改前改后各是什么"随时能复算。
  边界取法只受一条硬约束限制：`val_until + lead + horizon ≤ 前沿`，即
  `val_until ≤ 2024-05-31T01:13:37 − 7d00:15 = 2024-05-23T20:58:37`。取 `val_until = 2024-05-20`，
  留 3 天多的余量；`train_until = 2024-03-01`、`dev_until = 2024-04-15`，三段都落在工单密月份里
  （1 月 32 / 2 月 33 / 3 月 27 / 4 月 21 / 5 月 27 条）。

一处我自己列错、当场更正的推论
  计划里我写的是"那 1 866 行会自动退成 `censored`"。**实际不是**：因为 `val_until` 也一起挪进了覆盖
  区间，那批锚点（6–7 月）根本不再生成样本行 —— 它们是**消失了**，而不是变成删失。这条区别要紧：
  现口径下 `censored` 计数为 0，不是"闸门没起作用"，是"前沿已经把所有候选锚点都覆盖了"，
  于是**留下的每个负例都是观察到的**。真实复跑数字在下面。

审计看不到这一格，所以把它进载荷（只加诊断，不加规则）
  上一轮的结论是"审计 `passed=true` 却有 9.5% 假负例"。本轮补 `_coverage_entries()`
  （`prepare_data.py`）：`ticket_coverage_end` / `outcome_observed_until` / `rows_beyond_coverage`
  三项进 JSON 载荷；人读模式在缺口非零时多打一行
  `coverage: the latest ticket is ... and N of M row(s) are anchored later, so those labels are
  assumed rather than observed`。**没有**把它做成硬失败——前沿该取多长是输入事实，不是本层能裁决的，
  现在只保证它不再隐形。

变异证明（4 条，逐条杀到对应测试）
  C1 永远报 0 行 → KILLED（`test_a_frontier_past_the_last_ticket_reports_the_rows_it_invents_as_negatives`
     与人类摘要那条）
  C2 拿最早一条工单当覆盖终点 → KILLED（两条边界测试都红）
  C3 载荷里有、人读摘要里没有 → KILLED（只红人类摘要那条，正是它的分工）
  C4 数"越过前沿的行"而不是"越过工单的行" → KILLED
  fixture 天然就是"前沿晚于工单"的形状：工单最晚 `2024-04-07T12:00:00.000000001`，
  `BOUNDS.outcome_observed_until = 2024-04-30` ⇒ 23 行里 6 行越过覆盖，而审计照样 `passed=true`。
  这条测试钉的就是这个反差。

真实切片复跑（新边界，两条路径）
  - C raw：09:37:53 → 09:43:28（5 分 35 秒），退 0
  - D `--from-sorted`：09:43:29 → 09:49:24（5 分 56 秒），退 0
  - `config_hash` 两边同为 `19f363d1509b3359…`（换了 split 就换 hash，符合预期）
  - 覆盖块：`ticket_coverage_end == outcome_observed_until == 2024-05-31T01:13:37+00:00`，
    **`rows_beyond_coverage = 0`**
  - 51 个分区 sha256 逐分区相同，17 531 行按 `sample_id` 对齐后**文本差异 0 格**
    ⇒ 上一轮的归一渲染在新边界下同样成立
  - 审计：`rows=17 531`、`embargo_removed=1 463`、`passed=true`、`violations={}`
  - 逐划分正负例（这是本轮真正要的东西）：

    | 划分 | 行数 | 正样本 | 有正样本的单元 |
    |---|---|---|---|
    | train | 10 258 | 2 329 | 63 |
    | dev | 3 094 | 834 | 37 |
    | val | 2 246 | 608 | 26 |
    | embargo | 1 463 | 447 | 17 |
    | outside | 470 | 395 | 16 |

  - 与旧口径对照：旧表 19 540 行里消失的 **2 009 行全部 `label=0`，新增 0 行**，正样本总数
    4 613 一格没少 ⇒ 改前沿只砍掉了没人观察过的负例，没有砍掉任何一条真故障。
    `val` 从 **0 个正样本**变成 **608 个（26 个单元）**，这把尺子第一次能在 val 上算 F1。
  - 9 个单元（旧 195 → 新 186）从此一个样本都不产：它们的日志只在 2024-05-20 之后才有行，
    落在新 `val_until` 之外。这是划分的直接后果，不是新缺陷；真实序列号不写进本文档。

下一步
  1) 单元→`serial_number_type` 侧表 + 进配置指纹（写 submission 之前必须有）。
  2) 本地 evaluator：`dev` 与 `val` 各出一份**本地口径**分数，细则标 provisional。
  3) Linux 冒烟清单与给队长的一页问题清单。


## V1-10 (前置 6) 单元→serial_number_type 侧表进产物，并进配置指纹

为什么必须有
  官方交付要按 `serial_number_type` 分 A/B 两列报分数，而样本表里没有这一列：工单只覆盖**出过故障**
  的单元（切片上 140 条 / 200 单元），剩下 60 个静默单元拿不到类型。切片实测还确认了另一件事：
  真实事件表 24 列里**没有任何一列承载 SN 或类型**，所以目录名（`type_A`/`type_B`）是唯一的
  静态来源，工单那一列退化成校验位。

库层新入口 `build_unit_type_table(files, tickets)`（`smartmem_data.py`）
  列 `unit_id / serial_number_type / source`，`source ∈ {queue_directory, ticket, unresolved}`。
  口径三句话：目录优先（它是静态事实，不看标签）；工单只用来**交叉校验**；两者不一致**不是选择题，
  是坏输入**，直接 `SmartMemDataError` → 退 1，消息里只出现 `anonymize_unit` 后的 id。
  没被任何声明覆盖的单元记 `unresolved` 且类型留空 —— 拿错误率去猜类型就是"把标签泄漏化装成特征"。
  同一单元被列进两个声明不同的目录也是坏输入（`two queue directories`）。

CLI 接线（`prepare_data.py`）
  - 新分区族 `units/serial_type`（`UNIT_TYPE_PARTITION`），在 `_sample_run` 里跟样本分区一起排进
    `jobs`，所以它享受同一套 sha256 断点续跑；`--profile-only` 不写这个分区，但**照样把侧表算进
    config hash**，否则同一份入参在两种模式下会得到两个 hash。
  - `_config_payload` 新增 `unit_type_fingerprint`：对 `unit|type|source` 逐行拼串再 sha256。
    补的是 `_listing_fingerprint` 看不见的另一半 —— 它只记名字与体积，**换队列目录它毫无反应**，
    于是"把 200 个单元从 type_A 挪到 type_B"这种改动能让旧 out 目录继续跑完，产出按旧类型打分的表。
  - 载荷多 `unit_types`（rows/declared/unresolved 三个计数），人读摘要多一行
    `unit types: 200 of 200 unit(s) carry a declared serial_number_type, 0 unresolved`。
  - 一处必要的收口：`assembled` 读回时只能读 `sample_jobs`，把侧表分区也喂给 `_read_partition`
    会当场 `KeyError: 'prediction_time'`（它按样本表的列清单读列）。这也是本轮唯一"先红后懂"的地方。

变异证明（6 条，逐条杀到对应测试）
  M1 侧表不进 jobs → KILLED（4 条：续跑复用集、侧表内容、目录口径、可 join 性）
  M2 指纹里删掉侧表 → KILLED（`test_a_ticket_type_edit_is_caught_by_the_side_table_fingerprint`）
  M3 指纹只记 unit_id 不记类型 → KILLED（同一条，这正是"看不见挪目录"的等价变异）
  M4 目录与工单不一致时默默取目录 → KILLED（退 1 那条 + 库层"不打印序列号"那条）
  M5 unresolved 单元被塞一个猜的类型 → KILLED（夹具内容测试 + 库层 unresolved 测试）
  M6 目录声明的行 source 写成 ticket → KILLED（3 条）

真实切片复跑（两条路径，新目录 `out-raw4` / `out-sorted4`，10:19→10:31）
  - 两条都退 0，`config_hash` 同为 `2472df3d8cc1…`（因为指纹进配置了，与上一轮 `19f363d1…` 不同，符合预期）
  - **52 个分区（50 样本 + audit + units/serial_type）逐分区 sha256 相同，0 处不同**
    ⇒ `--from-sorted` 这条路径没有把队列身份弄丢（布局索引本来就是 `(queue, unit)` 复合键）
  - 侧表：200 行，`source` 全是 `queue_directory`，A 195 / B 5，`unresolved` 0
  - 与工单交叉校验：140 个有工单的单元全部命中、**类型冲突 0 处**；5 个 type_B 单元一条工单都没有
  - 样本侧数字与上一轮完全一致（`rows=17 531`，`rows_beyond_coverage=0`）⇒ 侧表是加法，没动标签
  - 切片上拿不到的东西：真实包里每个单元都在 `type_*` 目录下，所以 `ticket` 与 `unresolved` 两条分支
    在真数据上**没有被触发**，它们只被 fixture 覆盖。这条差距记在这儿，别当成已验证。

## V1-10 (前置 7) 本地 evaluator：F1 第一次可算，细则一律标 provisional

新增 `benchmark/smartmem/evaluator.py`（613 行）+ `tests/test_smartmem_evaluator.py`（376 行、11 条测试）。
入参 `--run-dir --ticket-file --predictions --split --beta --duplicate-alarm-rule --queue-aggregation
--lead --horizon --timezone --epoch-unit --unit-type-table --expect-config-hash --json`，沿用
`prepare_data.py` 的 `_Parser`/`Console`/`EXIT_*` 形状（没有 console script，测试直接调 `main(argv)`）。

三条契约，每条都有测试钉：
- **口径 provisional**：载荷与人类输出都带 `metric_spec_status: provisional`，本地分数只能和
  本地分数比。重复告警怎么计、两类队列怎么汇总都是命令行开关，不是常量；
- **不打印序列号**：载荷里只有计数与 `sample_id` 哈希，`test_no_serial_number_and_no_row_of_any_unit
  _reaches_the_output` 用 sentinel 单元名当探针；
- **不可评分 ≠ 0 分**：切片内没有任何告警落进标签窗时退 **4**（新增退出码），人类输出与 JSON 里
  都不出现 `f_beta`。把无标签窗口报成 `0.0` 会教读者怀疑每一个低分。

判分几何：命中窗 `[alarm - horizon, alarm - lead]` 是 `faultevolve.data.event_sampling` 标签规则
`failure ∈ [t + lead, t + lead + horizon]` 的镜像。哪条告警算"本切片必须覆盖"由**样本表的锚点**决定，
不由提交决定 —— 这是本轮唯一一次设计错了再改回来的地方。

**当天发现的设计错误（已改）**：第一版按"提交里出现过的单元"分队组打分，于是
(i) 模型不预测某台机器，那台机器的告警就不进分母，**什么都不预测的提交能买到 recall 1.0**；
(ii) 一个没有任何预测的队列直接从报告里消失。现在 `selection`（切片全部行）给分母、`called`
（提交行）给命中，M1 变异把分组改回 `called` 立刻红两条测试。真实切片上的对照：
漏掉 13/26 个正样本单元后 `fn=13`、recall 0.5，不再是一片干净。

变异证明（7 条，逐条杀到对应测试）
  M1 按提交行分组而非按切片分组 → KILLED（两条）
  M2 each-alarm 不看命中窗 → KILLED（聚合细则那条）
  M3 去掉"早于 history_end"的拒绝 → KILLED（流式约束那条）
  M4 别的切片的预测照打 → KILLED（跨切片拒绝那条）
  M5 mean-of-f1 退回 sum → KILLED（倾斜划分双队列那条）
  M6 空告警切片报 0 分而不是退 4 → KILLED（not_scorable 那条）
  M7 once-per-unit 不算漏报 → 第一版**存活**，补了 coarse 细则下的漏报断言后才 KILLED

真实切片本地分数（`out-raw4`，`--split dev/val`，其余默认，全部退 0）
  切片事实：dev 3 094 行 / 89 单元 / 834 正样本行 / 37 正样本单元，必须覆盖 37 条告警；
  val 2 246 行 / 70 单元 / 608 正样本行 / 26 正样本单元，必须覆盖 26 条告警。
  两份参考提交都不是模型分数，只是几何校验：

| 提交 | 细则 | dev F1 | val F1 |
| --- | --- | --- | --- |
| 切片内每行都预测 | each-alarm | 0.023635 | 0.022887 |
| 切片内每行都预测 | once-per-unit | 0.587302 | 0.541667 |
| 只预测 `label=1` 的行（oracle） | each-alarm | 0.08496 | 0.082019 |
| 只预测 `label=1` 的行（oracle） | once-per-unit | 1.0 | 1.0 |

  这张表是给队长的第一份证据：**oracle 在细规则下只有 0.08**，因为 15 分钟锚点频率让一条告警对应
  几十个正样本行，行级提交必然把 fp 打爆；而**粗规则下 oracle 恰好 1.0**，说明"点名正确单元"这条
  细则几乎不含时序信息。两条都不是官方口径，所以不跟 baseline 0.207 比。
  本切片的告警全落在队列 A（队列 B 的 alarms=0），所以 `sum` 与 `mean-of-f1` 在这份数据上给同一个数；
  双队列倾斜的差异只在 fixture 上被测试钉住，真实切片还没给出这种倾斜。

下一步
  1) Linux 冒烟清单与给队长的一页问题清单（判分细则这条现在有实测证据可问了）。

## V1-10 (前置 8) 两份清单交付，`--emit-dialect` 记延期

- `docs/runs/smartmem-linux-smoke.md`：服务器侧一条命令一档的冒烟清单。只列**当场能验**的事：
  `pyarrow` 是否可 import（`--format feather` 依赖它，本地 venv 已验、服务器未验）、队列目录大小写、
  `--profile-only` 不加 `--error-types` 也必须退 0（默认取值域一旦在全量数据上被证伪就该退 1 并列出
  没盖住的写法）、raw 与 `--from-sorted` 两条路径逐分区 sha256 对比、评一份参考提交确认能出数且
  空告警切片退 4、`knowledge_check`。每条都写了"看什么"，没写"应该没问题"。
- `docs/runs/smartmem-questions-for-leader.md`：压成一页、只剩六条要队长拍板的：判分细则（附本轮
  实测的 0.082 对 1.0 那张表）、验收方言、跳板与服务器路径、时区与日历日端点、无告警单元类型的
  官方来源、`outcome_observed_until` 的逐台真值。
- **延期一条：`--emit-dialect` 本轮不做。** 理由是它证不了它想证的东西：官方预计算特征表我们没有
  一份可对照的样例，反向转换器根本不存在，而列顺序在任何重建里都会先丢掉，所以最多只能证"值相等"、
  证不了"字节相等"。花几个小时做一个自己知道自己弱的等价器，不如把要问的话写进清单 —— 方言这条就是
  清单第 2 条。下一轮若拿到官方特征样例文件再评估。

## V1-10 (前置 9) 判分默认改成"SN 级去重 + 必须落窗"，并撤回"细则全自定"那句

起因是回答"还需要做什么"时去官方与本地找口径证据，翻到一份**逐字核录**：
`memory-predict/knowledge/官方判分规则_核录0926.md`（2026-09-26 浏览器实读 Codabench 3586 公告页
与 SmartMem Evaluation 页面，非转述）。它的 §3 把我们当作"没法自己判定"的判分细则回答了一半：

- 命中 = 某 SN 的**任一条**预测落在 `[故障 − 7d, 故障 − 15min]`；
- precision 分母 = **被预测的 SN 数（SN 级去重，多报几条不额外扣分）**；recall 分母 = 工单 SN 总数；
- §3b 定死 △tl=15min、△tp=7d 是官方固定值，β 是超参（β=1 即 F1）；
- §4 的流式三约束与本地 evaluator 已有的"预测时刻不得早于该行最后一条事件"同形。

**于是本轮上一版写下的两句话是错的，撤回**：README 里的"官方判分细则尚未公布"与问题清单第 1 条的
"两条全靠自定"。细则**页面原文**有，缺的是**可执行 scorer 源码**（拿到源码才能摘掉 `provisional`；
许可 CC BY-NC-SA 且禁止入库，所以也不能抄）。

代码只动 `benchmark/smartmem/evaluator.py`：

- 新增 `_count_sn_in_window()`，`--duplicate-alarm-rule` 三值
  `sn-in-window`（**默认**）/ `each-alarm`（§5.1 兜底协议，最紧）/ `once-per-unit`（最松，无来源支持）；
- 新增 `RULE_PROVENANCE`，每条细则随载荷与人类可读输出一起说清"这话说在哪"，`payload.rule_provenance`；
- 队列汇总措辞更正：页面原文把 P/R 定义在整个 SN 集合上 ⇒ `sum` 是照原文的读法，`mean-of-f1`
  降为敏感性检验；
- 三条口径边界写进 README/expert.md：本仓按 `split_key` 切片打分，**分母是切片内有窗的工单 SN**，
  不是官方那种全量工单 SN；官方"只统计考卷日历窗内预测"这层过滤本仓没有；
  两源窗左端差 15 分钟（FAQ `[−7d, −15min]` 对 Evaluation 反解 `[−7d−15min, −15min]`），取窄窗偏保守。

测试：`tests/test_smartmem_evaluator.py` 11 → **13 条**，SmartMem 家族 298 → **300 条**，全量
**804 → 806** 通过，失败集合仍是基线 `18 failed / 19 errors`。新增两条钉官方语义：一份点名但
无一落窗的提交在默认细则下必须是 `tp=0 fp=1 fn=1`（这条同时证明默认 ≠ `once-per-unit`）、
三条细则各自的出处必须随分数出门。

变异（`PYTHONDONTWRITEBYTECODE=1` + `-p no:cacheprovider`，整文件选择集，跑完 md5 还原，**6/6 KILLED**）：
M1 去掉落窗约束 → KILLED（点名不落窗那条）
M2 预测侧不去重（按行计 fp）→ KILLED（三瞬时那条 + 分母归属那条）
M3 默认留在 `each-alarm` → KILLED（4 条）
M4 出处不进载荷 → KILLED
M5 `sn-in-window` 指向紧计数器 → KILLED
M6 漏报不再算 fn → KILLED

200 单元真实切片复算（`D:/sm-slice200/out-raw4`，`config_hash 2472df3d…`，只读产物不重跑 prepare）：

| 提交 | 细则 | dev F1 | val F1 | dev tp/fp/fn |
| --- | --- | --- | --- | --- |
| 切片内每行都预测 | `sn-in-window`（默认） | 0.587302 | 0.541667 | 37/52/0 |
| 切片内每行都预测 | `each-alarm` | 0.023635 | 0.022887 | 37/3057/0 |
| 切片内每行都预测 | `once-per-unit` | 0.587302 | 0.541667 | 37/52/0 |
| 只预测 `label=1` 的行（oracle） | `sn-in-window`（默认） | **1.0** | **1.0** | 37/0/0 |
| 只预测 `label=1` 的行（oracle） | `each-alarm` | 0.08496 | 0.082019 | 37/797/0 |
| 只预测 `label=1` 的行（oracle） | `once-per-unit` | 1.0 | 1.0 | 37/0/0 |

**这张表里最要紧的一格是"默认与最松的那条在本切片上给同一个数"**：因为每个被点名的告警单元都恰好
有一条预测落在窗内（切片按 15 分钟网格造锚点，窗宽 7 天，锚点必然密）。⇒ 拉开一个量级的是
**去重与否**，不是时刻；两条去重读法只在"点名但无一落窗"时分道，而那种提交在这份真实切片上跑不出来，
只有合成 fixture 能演 —— 所以它被钉成测试而不是被展示成数字。
推论直接进问题清单第 1 条：页面原文口径下**一份不含任何模型的"跟着标签报"提交就拿满分**，
真正没定的是**有没有告警预算 / top-1%** 这类 precision 侧约束，不是配对方式。

下一步
  1) 任务定义三件套 `problem.md` / `prompt.md` / `init.py`（口径证据已到位，形状照
     `git show HEAD:benchmark/hdd_mvp/problem.md`）；
  2) evaluator 接进化闭环（`evaluate()`/`static_check()` + adapter 覆写 + `test_dataset_stubs.py` 迁移）；
  3) MVP 一页可跑清单。

## V1-10 (前置 10) 任务定义三件套：`problem.md` / `prompt.md` / `init.py`，全部挂在证据上

起因是用户那句"你去官方和本地再找找有没有口径内容，别自己编"。上一节已经把判分口径查到页面原文，
这一节把查到的东西落成文件，形状一律照仓内既有任务，不自创：

| 文件 | 形状来源 | 内容来源 |
| --- | --- | --- |
| `problem.md`（简体中文） | `git show HEAD:benchmark/hdd_mvp/problem.md`（`## Objective` + READONLY 注释 + 5 节） | §4.1-§4.2 候选合同、页面原文判分、真实切片实测 |
| `prompt.md`（英文） | `git show HEAD:benchmark/hdd_mvp/prompt.md`（Role/Task/Data/Score/Constraints/Reference） | 同上，措辞与 problem.md 逐条对齐 |
| `init.py` | `benchmark/hdd_mvp/init.py`（docstring 写 I/O 合同 + FEATURES 表 + 阈值扫描，79 行） | 只用四个可见文件，标签只来自 `train_labels.csv` |

`docs/plans/SMARTMEM_PHASE2_REQUIREMENTS.md` §4.2 定的输出是 `sample_id,score,alarm`，而本地 evaluator
今天读的 `--predictions` 是 `sample_id,prediction_time`。这不是冲突，是**同一件事的两层**：候选只负责
"哪一行报警"，时刻由 evaluator 从 index join 出来（§4.2 原话"evaluator 自行将 sample_id join 到本地
index，候选不得伪造告警时刻"）。所以 problem.md 写成候选面 `score,alarm`、判分面落窗，并在第 1 节明写
`--data-dir` 是那四个文件的**公开快照**（train 带标签、被评切片不带标签）。

**这条承诺现在还没兑现**：能把 `--data-dir` 快照切出来、能跑候选子进程的 `evaluate(program_path, …)`
是闭环那一步的活。今天真能跑的只有 `--predictions` 那条命令行（我用一份手搓快照验的 `init.py`，
脚本在临时目录，不进仓）。如果闭环那步回退，这份 problem.md 的第 1 节要一起改回来，不能留假合同。

实测（`D:/sm-slice200/out-raw4` + `raw/ticket.csv` + `split-v2.yaml`，只读产物）：

| 切片 | 行数 | index 覆盖 | 告警数（=被点名单元数） | 默认口径 F | P | R | tp/fp/fn |
| --- | --- | --- | --- | --- | --- | --- | --- |
| dev | 3 094 | 3 094/3 094 | 40 | **0.441558** | 0.4250 | 0.4595 | 17/23/20 |
| val | 2 246 | 2 246/2 246 | 32 | **0.344828** | 0.3125 | 0.3846 | 10/22/16 |

两点必须说清：① 这两个数走的是 `sn-in-window`（暂定口径），且 `each-alarm` 给出**同一个数** —— 一份
"一单元只报一次"的提交下，贪心配对没有可发挥的余地，两条读法重合；② 它比上一节那两份几何校验提交
（每行都报 / 跟着标签报）更像模型，但**仍然不校验模型好坏**：切片正样本行密度约 26%，与现场千分位基率
差两个量级，换把尺子就不是这个数。所以这里只报"链路能跑 + 分数可复现"。

绝对概率阈值为什么不行，是被实测逼出来的：第一版按训练片概率分位取绝对 cut，dev 上 **0 条告警**
（F1=0，且是"没报"而不是"报错"）；改成分位数迁移（训练片扫 50-99 分位选 SN 级代理 F1 最优那一档，
把同一档套到被评片）后 dev 40 条 / val 32 条。这条差异写进 `init.py` 的 docstring 与 problem.md §4，
因为它正是 problem.md 第 2 节"跨切片密度不可比"那句话的具体后果。

测试：新增 `tests/test_smartmem_seed.py` **4 条**（本仓静态检查 / 填满 index 且一单元至多一次且报在
最响行 / 缺列快照仍可跑 / 无正例训练片必须非零退出并给可读消息；外加钉住四文件齐备与两份文档的分数
公式、落窗 join 措辞不许漂）。SmartMem 家族 300 → **304** 条，全量 **806 → 810** 通过，
失败集合仍是基线 18 failed / 19 errors。

变异（整文件选择集，`PYTHONDONTWRITEBYTECODE=1` + `-p no:cacheprovider`，md5 逐字节还原）：

| 变异 | 结果 |
| --- | --- |
| M1 改成"所有过线的行都报"（去掉一单元一次） | KILLED |
| M2 去掉缺列快照的零填充（NaN 进 sklearn） | KILLED |
| M3 让种子去 `../ticket.csv` 拿标签 | KILLED（静态检查 + 两条运行测试一起红） |
| M4 无正例训练片改为悄悄交全零 | KILLED |
| M5 输出列 `alarm` 改名 `flag` | KILLED |
| M6 problem.md 把 `event_f1` 换成 `sample_f1` | KILLED |
| M7 prompt.md 同上 | KILLED |
| M8 problem.md 撤掉"时刻由 evaluator join"这句 | KILLED |
| 早期一版：删掉 problem.md 某一句里的 `provisional` | **SURVIVED**（该词在文档里出现多处，presence 断言抓不到单点删除） |

最后那条 SURVIVED 没被藏起来：它说明"某个词还在不在"这种断言只能防整段丢失，防不了口径被挪到别处。
所以真正留下的文档断言钉的是**分数公式**与**落窗 join 那句**（各文件里唯一出现），这是 M6-M8 能红的原因。

顺带脱敏一处违规：前置 3 那 5 个单元写的是**真实序列号**，按本仓规则不该进文档，现已改成 单元#1-#5
（原值只在本地切片产物里）。它们跟着更早的提交出过一次门，分支是私有的，但规则就是规则，记在这里。

README 更正：原来那句"本任务目录缺的是另外三件套"作废，改成三件套已补、并写明 `fe doctor` 现在
`task_files` 过、`task_data`/`evaluate` 仍不过（`REQUIRED_DATA_FILES` 还写着 `public/*` 那套从没被
写出来的名字）。`docs/datasets/smartmem.md` 依旧不动（sparse-checkout 排除在外），过期状态在本节记录。

下一步
  1) 闭环接线：`candidate_runner.py` + evaluator 的 `evaluate(program_path)` + adapter 覆写与
     `REQUIRED_DATA_FILES` 换成 `prepare_data.py` 真写的布局 —— 这一步兑现 problem.md 第 1 节的快照合同；
  2) MVP 一页可跑清单。

## V1-10 (前置 11) 闭环接线：候选子进程 → 公开快照 → 本地判分，一条命令能跑通

兑现上一节欠的那句"这条承诺现在还没兑现"。改动只碰 4 个文件，**通用演化层一行没改**
（`stub_base.py` / `famou_adapter.py` / `cloud/engine.py` / `worker/runner.py` / `registry.py` 全部没动）：

| 文件 | 加了什么 |
| --- | --- |
| `benchmark/smartmem/candidate_runner.py`（新，约 230 行） | 快照渲染 + 子进程执行 + 超时 + 截尾脱敏 |
| `benchmark/smartmem/evaluator.py`（+324 行） | import 级 `evaluate(program_path, …)` 与 `static_check(source)` |
| `src/faultevolve/tasks/smartmem_adapter.py`（+72/-4） | `load_task` 真读三件套、覆写 `evaluate`、给 `constraints`、换 `REQUIRED_DATA_FILES` |
| `tests/test_dataset_stubs.py` | 那条"必须抛 `DataNotPreparedError`"拆成两条 |

签名照需求文档 §4.1 逐字实现：`evaluate(program_path, timeout=900, split="dev", *, data_root=None,
seed=20260926, ticket_file=None)`，返回 `validity / combined_score / cost_time / error_info / metric`，
`combined_score = 100 × f_beta`（`SCORE_SCALE`）。

三处位置选择各有理由：
- 执行器独立成 helper 是 `SMARTMEM_PHASE2_TODO.md` V2-03 的建议 —— 不可信代码的执行与可信的评分分开，
  **评分仍然只在 evaluator 里**。
- `evaluate()` 放在 evaluator 是需求文档 §4.1 指定的签名与位置。副作用必须为零：
  `codecheck.full_check` 是用 importlib 载入本文件再调 `static_check` 的，任何模块级读数据都会污染每次评审。
- adapter 的 `evaluate` 显式传 `data_root=` 而不是改全局 env：一次 run 的多个 worker 共享进程，
  谁后写 env 谁就决定别人看到哪份数据。
- `test_dataset_stubs.py` 里 `smoke_test` / `build_smoke_data_dir` / `load_task` 空目录**仍抛**
  （`evolve.yaml` 里 smoke 就是 `enabled: false`），`evaluate` 改成**报告而不是抛**：
  闭环里抛异常会让一个候选炸掉整轮，`validity=0` + 可读 `error_info` 才是评测该有的形状。
- `REQUIRED_DATA_FILES` 从没人写过的 `public/*` 换成 `manifest.json` +
  `partitions/{samples,audit,units/serial_type}`。

三个输入的定位一律"显式参数 → 环境变量 → 就地扫描"，不发明新约定：`SMARTMEM_DATA_ROOT`（run 目录）、
`SMARTMEM_TICKET_FILE`（缺回复用 `prepare_data.TICKET_NAMES` + `_find_tickets` 扫，因为
`data/manifest.py:253-260` 证实 manifest 只存摘要不存路径）、`SMARTMEM_TICKET_EPOCH_UNIT`。真实工单
`raw/ticket.csv` 的时间戳是**秒**，所以这一项必须给 `s`；不给会按默认单位读，读出来的窗整段错位。

两份合同（候选面 `sample_id,score,alarm` vs 判分面 `sample_id,prediction_time`）在
`_candidate_predictions()` 里做一次 join：候选只说"哪一行报"，**时刻从 index 取**，`alarm` 不是 0/1、
`sample_id` 是 index 里没有的、同一行报两次，都在这里拒；被拒的行不算预测，而不是算一条坏预测。

打分走**进程内**（`_score_in_process()` 复用 CLI 的 `_report` + `Console(json_mode=True)`），不是再起一个
子进程：这样闭环分数与命令行分数**结构上不可能分叉**，并钉进测试
`test_loop_score_equals_cli_score`（`pytest.approx(ev.SCORE_SCALE * payload["f_beta"])`）。

真实切片实测（`D:/sm-slice200/out-raw4` + `raw/ticket.csv` + `split-v2.yaml`，**只读产物**，新产物只写进
`D:/sm-slice200/loop-artifacts`）：候选 = `init.py` 自身（`spec.init_code`，即引擎里的第 0 号候选）。

| 入口 | validity | combined_score | 单次墙钟 |
| --- | --- | --- | --- |
| `adapter.evaluate(init_code, spec)`，split=dev | 1.0 | **44.1558** | 2.06 s |
| `evaluator.evaluate(init.py, split="val")` | 1.0 | **34.4828** | 2.11 s |

dev 那份 metric：`duplicate_alarm_rule=sn-in-window`、`metric_status=provisional`、P 0.425 /
R 0.459459、tp-fp-fn 17/23/20、alarms 37、named 40、rows_scored 3 094、units_scored 89、
queues [A, B]、`config_hash=2472df3d…`。val 走同一套 stamp。

这两个数与前置 10 命令行跑出来的 0.441558 / 0.344828 **逐位相同** —— 这就是"闭环与 CLI 是同一把尺子"的证据，
不是又一次"差不多"。payload 与 stdout 里 `sn_\d+` 匹配 0 处（`candidate_runner._tail` 用 `SERIAL_IN_TEXT`
把子进程任何输出里的序列号换成 `[unit]`，`MAX_CAPTURED_CHARS=20000` 截尾）。

`fe doctor --task-dir benchmark/smartmem` 现在三行都绿：`✓ task files ok`、`✓ adapter smartmem ->
SmartMemAdapter`、`✓ data dir D:\sm-slice200\out-raw4; ok`。

一条必须写下来的坑：**`fe evolve local --task-dir benchmark/smartmem --mock` 在本机（Windows）跑不了**。
`src/faultevolve/discovery/sandbox.py:7` 顶层 `import resource` 是 POSIX-only 模块，于是
`import faultevolve.cloud.engine` 直接 `ModuleNotFoundError`。这不是本轮接线的产物 —— 全量基线那 18 条
失败里，`test_knowledge.py::TestEngineTaskAgnostic` 与
`test_jev_screening.py::test_cloud_modules_task_agnostic`、
`test_doctor_task_checks.py::test_evolve_local_stub_dir_message` 三条一直是同一条原因。按计划的回退条款本该
"跑不通就整步回退"，这里判定**不回退**：引擎实际调用的就是 `load_task / static_check / evaluate / constraints`
这四个方法，它们已被 21 条测试 + 一次真实切片跑通验到；缺的只是那个需要 POSIX 的 CLI 壳子，**真 CLI 那一轮
留给 Linux 服务器**（与"服务器与跳板"那条待决项是同一件事）。

测试：新增 `tests/test_smartmem_loop.py` **21 条**（快照只四份文件且两侧都剥 `label`/`split_key` / index
全覆盖且队列名进 metric / 未知 split 与无 partitions 明确拒绝 / 执行合同与密钥清除与序列号脱敏与超时归 0 /
闭环分数 == 命令行分数 / "被拒的行不是预测" / 静态检查拒标签源 / 幽灵 sample_id / `alarm` 非 0-1 / 重复行 /
未备数据给可读消息 / metric stamping / `data_status` ok 且不再找 `public/` / adapter 显式传 data_root（把
`SMARTMEM_DATA_ROOT` delenv 后仍出同一分）/ constraints 真被换上 / `static_check` 两个分桶）。
SmartMem 家族 10 → **11 文件、304 → 325** 条，加上 `test_dataset_stubs.py` + `test_adapter_registry.py`
共 **349** 条全绿；全量 **810 → 832** 通过，失败集合仍是基线 18 failed / 19 errors（未新增一条）。

变异（整文件选择集，`PYTHONDONTWRITEBYTECODE=1` + `-p no:cacheprovider`，跑完 md5 逐字节还原）：**14/14 KILLED**。

| 变异 | 结果 |
| --- | --- |
| M1 快照把 `label` 交给候选 | KILLED |
| M2 快照只剥 `label`、漏 `split_key` | KILLED |
| M3 index 不再给队列命名 | KILLED（首版 SURVIVED） |
| M4 子进程保留父环境密钥 | KILLED |
| M5 输出截尾不再脱敏序列号 | KILLED |
| M6 超时当异常抛出（炸掉整轮） | KILLED |
| M7 静态检查不再拒工单/标签源 | KILLED |
| M8 没人认领的行仍算预测 | KILLED（首版 SURVIVED） |
| M9 幽灵 `sample_id` 变成一条预测 | KILLED（首版没打上） |
| M10 闭环不 honour 传进来的 `data_root` | KILLED |
| M11 `REQUIRED_DATA_FILES` 退回没人写的 `public/*` | KILLED（首版没打上） |
| M12 用回 stub 的默认 constraints | KILLED |
| M13 `evaluate` 退回抛 `DataNotPreparedError` | KILLED |
| M14 让种子过不了它必须过的静态检查 | KILLED |

那四条首版没红的原因，都在测试或变异脚本自己身上，不在被测代码：M3 断言只看列在不在，改成必须出现
真实 `A`/`B` 队列值才红；M8 是合成 fixture 的 dev 行只剩一个单元，SN 级去重把差异吃掉了，改成钉
`predictions_written` 并在真实切片上演示（named 1 → 89、分数 5.26 → 58.73）；M9 是 needle 与
`_called_rows` 里一行文本撞上，两行上下文才唯一；M11 是工作树 CRLF（`core.autocrlf=true`）而 needle
是 LF，加 `splice()` 按文件实际换行符重拼才命中。改完 14 条全红，且 M8 在真实切片上量出十倍分差 ——
记在这儿是因为"合成 fixture 绿"不等于"口径被钉住"。

脱敏与依赖自查：本轮没有一个文件出现真实序列号（`sn_\d+` 全局 0 处），`D:/sm-slice200` 已有产物只读、
新产物只写进新建的 `loop-artifacts`；`benchmark/hdd_mvp/**` 未碰，`docs/datasets/smartmem.md` 未碰
（仍在 sparse-checkout 之外），未 import 另一条赛线的任何代码。

下一步
  1) 两个已知小洞：`_config_payload`（`prepare_data.py:635-668`）纳入渲染策略指纹 + `pyproject.toml` 补 `pyarrow`；
  2) MVP 一页可跑清单（判分三口径对照 + 本轮闭环实测数）；
  3) Linux 服务器上补跑一次真的 `fe evolve local --mock` 一轮（本机因 `import resource` 跑不了）。

## V1-10 (前置 12) 渲染策略进配置指纹，`pyarrow` 进依赖声明

两处都是 dev log 自己记过的欠账，这次一起收。改动 4 个文件、纯新增（`git diff --numstat`：
prepare_data +7 / smartmem_data +24 / 测试 +46 / pyproject +2），没有一行删除。

**洞 1：同一 `config_hash` 下可以混两种渲染口径。** 前置 4 把 dtype 归一做成
`canonicalize_feature_types`（`smartmem_data.py`）之后，`_config_payload`（`prepare_data.py:635` 起）
仍然只列 19 项**调用参数与输入指纹**，没有一项描述"声明的 dtype 怎么落成字节"。后果是旧口径的 out 目录会被
`--resume` 当成"已完成"续跑：续跑分支只信 `config_hash`，于是同一份 manifest 里一半分区按旧写法、
一半按新写法。

修法与侧表那一条同构（前置 6 的 `_unit_type_fingerprint` 已经在做同一件事的另一半）：新增
`RENDER_POLICY_VERSION = "smartmem-render-v1"` 与 `render_policy_fingerprint(manifest=FEATURE_MANIFEST)`，
把 `name|dtype|window|sources` 排序后连同策略版本 sha256，作为一个字段进 `_config_payload`。
**指纹进哈希而不是原表**，因为哈希要保持定长、且 manifest 本身几百行不该被抄进 manifest。

两条路都堵上了：① 声明变了（`FrequencyMHz` 从 `int64` 改 `float64`、或某列被增删）→ 指纹变；
② 声明没变但**规则**变了（`canonicalize_feature_types` 里改一个分支的名字看不见）→ 只有把
`RENDER_POLICY_VERSION` 从 v1 升到 v2 才会变。所以版本常量必须显式写进仓，且注释写明"改渲染规则时抬它"。

一条顺带确认的边界：`D:/sm-slice200/out-raw4` 这些**已产出**的切片记录的是旧 `config_hash`
（`2472df3d…`），本轮不改写它们（只读产物），也不影响打分 —— evaluator 读 manifest 里记下的哈希，
不重算。所以这一步的可见效果是：**从今天起新跑的 out 目录哈希与昨天不同**，且拿昨天的 out 目录
`--resume` 会退 2 而不是静默续跑。真实切片闭环复跑一次照旧 dev 44.1558 / val 34.4828，未受影响。

**洞 2：`pyarrow` 只活在我本机 venv 里。** `--format feather` 与真实包直读都硬依赖它，
`pyproject.toml` 的 `dependencies` 却没有。Linux 侧冒烟（`smartmem-linux-smoke.md` 第 1 步就是
`import pandas, pyarrow`）会第一眼踩。已补 `"pyarrow>=15"`，并加一条测试钉住声明本身
（`test_feather_is_a_declared_dependency_not_a_local_accident`）—— 这条测试看起来很笨，但它把"只在某台
机器上装过"这种状态变成可判定的事；上一版 `docs/runs/smartmem-input-evidence.template.md` 里那句
"是否进 pyproject（当前是我自建 venv 补装的）"就是它欠的账。

测试：`tests/test_smartmem_prepare_cli.py` 89 → **93** 条（新增 3 条：`--resume` 在策略指纹变化时退 2 /
指纹跟声明变 / 指纹跟策略版本变；外加依赖声明 1 条）。SmartMem 家族 325 → **329** 条，
加 `test_dataset_stubs.py` + `test_adapter_registry.py` 共 **353** 条全绿；全量通过 832 → **836**，
失败集合仍是基线 18 failed / 19 errors。变异 4/4 KILLED，每个变异**只有对应那一条红**，
三个文件跑完 md5 逐字节还原：

| 变异 | 结果 |
| --- | --- |
| V1 `_config_payload` 去掉渲染策略字段 | KILLED（退 2 那条红） |
| V2 指纹不看 manifest、返回固定值 | KILLED |
| V3 指纹不把版本常量拼进 body | KILLED |
| V4 `pyproject.toml` 撤掉 `pyarrow` | KILLED |

**仍然不做、记在这里的两条**（都不是遗漏）：`manifest.json` 顶层 `status` 永远停在 `open`
（`data/manifest.py:261` 只在创建时写，没有任何步骤改成完成态，所以"跑完"与"跑断"在顶层看不出来）；
`--chunk-rows` 未暴露（`io.py:42` 的 `DEFAULT_CHUNK_ROWS` 写死，归并阶段写小文件很慢，是吞吐问题不是正确性）。

下一步
  1) MVP 一页可跑清单（判分三口径对照 + 前置 11 闭环实测数 + 本轮 93 / 家族 329 的测试账）；
  2) Linux 服务器上补跑真 `fe evolve local --mock` 一轮。

## V1-10 (前置 13) MVP 一页可跑清单：每格现场实测，两处旧数字被当场改掉

新增 `docs/runs/smartmem-mvp-demo.md`（纯文档，代码零改动）。规则是**页面上每一个数、每一个退出码、
每一个墙钟都必须是本轮在真机上跑出来的**，跑不了的那一条就写在"本机跑不了"那一节，不装作能跑。

实测记录（驱动脚本在临时目录，不进仓）：

| 单元格 | 实测 |
| --- | --- |
| `--profile-only`（one-unit 快样，新目录） | 退 0 / 0.6 s / hash `64b807882e10…` |
| `raw4.json` 读数 | declared 200 / rows 200 / unresolved 0，`events raw-files`，`2472df3d8cc1…` |
| 两条路径逐字节 | `out-raw4` 与 `out-sorted4` 各 53 个文件，`partitions` 下 52 个 sha256 逐行相同 |
| 判分三口径（val，oracle 提交） | `sn-in-window` 1.0 / `once-per-unit` 1.0 / `each-alarm` 0.082019 |
| 队列汇总敏感性 | `--queue-aggregation mean-of-f1` 与 `sum` 同一个数 1.0 |
| 不可评切片 | 只给表头的工单 → **退 4**、`scoreable false`，reason 点明工单里没有告警，**没报 F1=0** |
| 复现护栏 | `--expect-config-hash 000…0` → 退 1，消息同时点出目录记的前缀与本次所求的前缀 |
| 闭环一轮 | `evaluate(init.py, dev)` → `1.0 44.1558 2.06`，`queues ['A','B']`，`sn_\d+` 0 处；val 34.4828 |
| `fe doctor` | 任务三项 ✓，整页退 1（只因为没设 API key）；**必须先设 `PYTHONIOENCODING=utf-8`** |
| 测试账 | 家族 329 / 加 stubs+registry **353 passed / ~41 s** / 全量 **836 passed, 18 failed, 1 skipped** |
| 换机兜底 | 清掉四个 `SMARTMEM_*` 后 prepare_cli + evaluator + loop **127 passed / ~28 s**，不碰 `D:` 盘 |

表格里为了排版砍掉的细节，页面上都还在：三口径那四条各带 `rows_scored 2246`、`units_scored 70`，
各 0.7 s；逐字节那一条的对拍命令是 Git Bash 里 `find partitions -type f | sort | xargs -r sha256sum`
两份摘要相比（0.2 s），唯一不同的是 `manifest.json`；`fe doctor` 那条的 GBK 坑是
`UnicodeEncodeError`，本轮现场踩过两次。

两处旧数字、一个"看着能跑"的页面被这轮实测改掉，都记下来：

1. **"与工单交叉校验 836/836"** —— 我在收窄给队长那一页时把两个上下文串了：`836` 是**全量镜像整张
   告警表**的行数与不同 SN 数，本 200 单元切片上有工单的单元只有 **140** 个（`已实测` 见前置 6）。
   已按前置 6 的原话改成"140 个有工单单元全部命中、类型冲突 0 处"，并在文末备查里保留 836 的真实出处，
   免得下一个人又拿它当切片数字用。
2. **"划分不可评时退 4"这条我原本准备的命令是错的** —— 想用 `--split embargo` 去演"没东西可评"，
   实测退的是 **1**（`608 prediction(s) were made on rows outside the 'embargo' slice`：那是**输入用错**，
   不是无可评），`_not_scorable()` 只有两条入口且都要求"切片的告警集为空"。改成给一份只含表头的工单，
   才真退 4。这条差一点就写进演示页变成"预期退 4 结果现场翻车"。
3. **演示页的 PowerShell 命令"看着能跑"，实际两块跑不动** —— 这轮把页面里 11 个 `powershell` 代码块
   逐块抠出来存成 `.ps1`、用 Windows PowerShell 5.1 真跑了一遍，抓到两个坑：
   ① 路径存在变量里时**必须**用调用运算符 `& $PY`，写成 `$PY benchmark/…` 会被当表达式解析，
   当场报「表达式或语句中包含意外的标记」；② 第 12 行那段 here-string 里的 python 代码原本用双引号，
   PowerShell 传给原生 exe 时把双引号吞了，报 `NameError: name 'benchmark' is not defined`，
   python 侧改用单引号才通。两条都补进了页面的"前置"，修完 11 块的退出码与预期逐格相符
   （0/0/0/0/4/1/0/1/0/1/0，bash 那块另在 Git Bash 里跑）。顺带按这次实跑更正四处墙钟：
   不可评切片 0.5→0.7 s、doctor 0.9→1.0 s、全量测试 98→107 s、换机兜底 32.6→28.9 s。
   还记一条给以后写 `.ps1` 的人：**存盘要 UTF-8 带 BOM**，PowerShell 5.1 无 BOM 时按 ANSI 读，
   中文注释会乱。

`smartmem-questions-for-leader.md` 按计划从六条压成**三条要答案**（判分两点确认 / 验收方言 / 服务器与跳板），
时区端点、静默单元类型来源、随访逐台真值这三条挪进文末备查并注明"已按现状定默认、不阻塞"；
服务器那条补了本轮新增的用途：它是补齐真 `fe evolve local --mock` 的唯一途径。
`benchmark/smartmem/README.md` 顶部加了指向这两页的链接。

下一步
  1) Linux 服务器上补跑真 `fe evolve local --mock` 一轮（唯一还欠的"整条引擎跑通"证据）；
  2) 判分第 1 条那两个确认（`serial_number_type` 是否作废命中 / 日历窗过滤）拿到答案后动 `_report`；
  3) 吞吐两项：`--chunk-rows` 暴露 + 归并攒够 N 行再落盘；manifest 顶层 `status` 完成态。
