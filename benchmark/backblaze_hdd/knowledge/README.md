# HDD failure-prediction knowledge pack (FaultEvolve / hdd_mvp)

Built 2026-09-28 for the ERA-style hook `get_era_knowledge_cards` in
`src/faultevolve/cloud/selection.py`.

## Files
- `sources.yaml`: 42 entries (41 external sources + `BENCH`, which is the repo benchmark itself). Each has title, authors, year, venue, URL, DOI/arXiv id where available, how it was retrieved, and a 1-2 sentence takeaway.
- `cards.jsonl`: 51 knowledge cards. Required fields: id, title, category, claim, rationale, applicability, expected_effect, risk, source_ids, tags. Extra fields:
  - `impl_hint`, `priority` (1 = try first), and `evidence` (`paper` | `benchmark`);
  - hook-compatible aliases: `idea` (= claim) and `source` (= joined source_ids), matching the docstring keys title/source/idea/impl_hint/risk.
- `build_cards.py`: the single source of truth for the cards. Edit it, then run `python3 build_cards.py` to regenerate `cards.jsonl`.
- `expert.md`: a Chinese expert direction doc, ranked by expected value for this benchmark.
- `raw/`: raw arXiv API responses (`arxiv_*.xml`, `arxiv_all.json`).
- `arxiv_list.txt`: the de-duplicated arXiv hit list.

Category counts: feature_engineering 15, model 6, evaluation 6, pitfalls 6, thresholding 5, labeling 4, imbalance 3, transfer 3, ensembling 3.

## Benchmark alignment
The cards are aligned with what the benchmark actually reads and scores. Files read via the GitHub MCP: `problem.md`, `evaluator.py`, `prepare_data.py`, `init.py`, `prompt.md`, and `FAMOU_任务说明.md`. The facts the cards depend on:
- Label horizon: failure in (c, c+7]. A positive's cutoff is failure_day - k, with k uniform in 1..7.
- History: at most 14 days.
- Negatives: still alive at c+7, weight about 10.
- Score: ROS formula and weights, plus the FAR budget of 0.2%.
- Bootstrap: 200 stratified resamples of F1, scored at the 10th percentile.
- Runtime: time_factor = min(1, 600/runtime), with a 900 s hard limit.
- Static-check regexes: the forbidden tokens that make a candidate invalid.
- Dependencies: pandas, numpy, sklearn, lightgbm, scipy only.

## Search method (reproducible)
1. **arXiv API** (`https://export.arxiv.org/api/query`, over HTTPS; plain HTTP returned empty bodies). The box's IP got HTTP 429 after a few calls, so the remaining queries went through the WebFetch tool. Queries:
   - `all:"disk failure prediction"` (max 30)
   - `abs:SMART AND abs:"hard drive" AND abs:failure`
   - `abs:Backblaze` (max 40)
   - `abs:"hard drive" AND abs:failure AND abs:prediction` (max 40)
   - `ti:disk AND ti:failure` (max 50)
   - `abs:"hard disk" AND abs:"remaining useful life"`
   - `ti:SSD AND ti:failure`, `abs:"disk failure" AND abs:"transfer learning"`, and `abs:"disk failure" AND abs:online`: few or no relevant hits
   - `ti:drive AND ti:failure`: mostly autonomous-driving noise, discarded
2. **Semantic Scholar Graph API** (`/graph/v1/paper/search`). Every request returned HTTP 429 (unauthenticated rate limit), both from the box and through WebFetch, so it contributed nothing. With an API key, re-run: `curl -G https://api.semanticscholar.org/graph/v1/paper/search --data-urlencode "query=disk failure prediction SMART" --data-urlencode "fields=title,authors,year,venue,externalIds,citationCount" -H "x-api-key: $S2_KEY"`.
3. **Web search** (Google-Scholar-style queries through the WebSearch tool), one per known classic:
   - Pinheiro FAST'07; Schroeder & Gibson FAST'07
   - Botezatu KDD'16; Xu et al. ATC'18 (CDEF); Lu et al. FAST'20
   - Mahdisoltani ATC'17; RAIDShield FAST'15; Zhu MSST'13; Li DSN'14 and SRDS'16
   - Murray JMLR'05; Hughes IEEE TR'02
   - Xiao ICPP'18 (ORF); StreamDFP ICDCS'20; TLDFP ICPP'19
   - PAKDD 2020 disk-failure competition; Kadekodi HeART FAST'19
   - SSD field studies (Narayanan SYSTOR'16, Schroeder FAST'16, Alter SC'19); WEFR DSN'21
   - Aussel ICMLA'17; Xu (Chang) IEEE TC'16; data leakage in HDD failure prediction (Grillmeyer ICPE'25); Pinciroli RAMS'22
   - General methods: LightGBM NeurIPS'17, Saito & Rehmsmeier PLOS ONE'15, Lipton et al. (F1 thresholding), SMOTE JAIR'02
   - Backblaze blogs: SMART stats 2016, Drive Stats 2024, bathtub curve 2025, dataset page
4. **WebFetch** to verify details: the full StreamDFP PDF, the Backblaze SMART-stats blog, the bathtub-curve blog, the dataset page, and researchr records for authors and venues (TLDFP, ORF, Aussel, WEFR).

Rule used: a source is listed only if its page or record was actually returned by one of these tools. Author lists that the tools did not fully show are truncated with "et al." or initials, and fields that were not retrieved are marked as such (the PAKDD volume editors, for example).

## Known gaps
- Semantic Scholar was unusable (429), so there are no citation counts and no snowballing through citation graphs.
- Some paywalled full texts were not read (IEEE/ACM, the PAKDD chapters, the ICPE leakage paper). Their takeaways come from abstracts or search summaries only.
- Few sources on SSD-specific or online/streaming methods apply directly to this offline HDD task. They are included only for drift and robustness ideas.
- Seagate's raw encoding of smart_1/7 (packed error/operation counters) is practitioner knowledge that no retrieved source confirmed. It is therefore only implied (per-model rank normalisation, FE08) and never stated as fact.
- No card has been checked against actual val ROS yet. `expected_effect` values are literature-based priors and should be recalibrated from FaultEvolve run logs.
