"""V1-08: benchmark/smartmem/knowledge - the SmartMem knowledge pack.

A knowledge pack is the artefact the plan's "deliver knowledge" half is made of, so the tests check
the things that make knowledge trustworthy rather than its length: every card has to say where the
claim came from, when it does not apply, and what could go wrong; every source has to be something
somebody actually read; and nothing may leak a serial number or a private path into a shared file.

The loader schema is reused unchanged - this pack is data, not a new format - so most of what is
checked here is what the loader does NOT check: source foreign keys, prose fields, evidence classes
and namespace.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import yaml

from benchmark.smartmem import knowledge_check
from faultevolve.knowledge.loader import VALID_CATEGORIES, load_cards
from faultevolve.knowledge.retriever import (
    CardRetriever,
    RetrievalContext,
    compute_tag_match_score,
)

REPO = Path(__file__).resolve().parents[1]
PACK = REPO / "benchmark" / "smartmem" / "knowledge"


def read_pack() -> tuple[list, list[str]]:
    cards, errors = load_cards(PACK / "cards.jsonl")
    return cards, errors


# ------------------------------------------------------------------- the files exist


def test_the_pack_ships_the_four_expected_files():
    for name in ("cards.jsonl", "sources.yaml", "expert.md", "README.md"):
        assert (PACK / name).is_file(), f"{name} is missing from the pack"


def test_the_loader_accepts_every_card():
    cards, errors = read_pack()
    assert errors == []
    assert len(cards) >= 15


def test_the_validator_finds_nothing_to_fix():
    assert knowledge_check.validate_pack(PACK) == []


def test_the_summary_counts_match_the_files():
    summary = knowledge_check.pack_summary(PACK)
    cards, _ = read_pack()
    sources = knowledge_check.load_sources(PACK / "sources.yaml")
    assert summary["cards"] == len(cards)
    assert summary["sources"] == len(sources)
    assert sum(summary["categories"].values()) == len(cards)
    assert sum(summary["evidence"].values()) == len(cards)


# ------------------------------------------------------------------- namespace and schema


def test_the_ids_live_in_the_smartmem_namespace():
    cards, _ = read_pack()
    ids = [card.id for card in cards]
    assert all(card.id.startswith("SM-") for card in cards), ids
    assert len(ids) == len(set(ids))
    # the HDD pack uses bare FE*/M*/T* ids; a renamed copy of one would collide on read
    assert not any(re.fullmatch(r"(FE|M|T)\d+", card.id) for card in cards)


def test_no_new_category_was_invented_for_this_domain():
    cards, _ = read_pack()
    used = {card.category for card in cards}
    assert used <= VALID_CATEGORIES, used - VALID_CATEGORIES
    assert len(used) >= 5


def test_the_prose_fields_the_plan_asks_for_are_filled_in():
    cards, _ = read_pack()
    for field in knowledge_check.REQUIRED_PROSE:
        empty = [card.id for card in cards if not getattr(card, field).strip()]
        assert empty == [], f"{field} is empty on {empty}"


def test_every_evidence_class_is_one_of_the_documented_ones():
    cards, _ = read_pack()
    bad = {card.evidence for card in cards} - knowledge_check.ALLOWED_EVIDENCE
    assert bad == set()
    # a pack that only quotes papers hides the fact that nothing was run yet
    assert {card.evidence for card in cards} >= {"paper", "official", "user_run"}


# ------------------------------------------------------------------- sources


def test_every_source_id_resolves_and_every_source_is_cited():
    sources = knowledge_check.load_sources(PACK / "sources.yaml")
    cards, _ = read_pack()
    cited = {source_id for card in cards for source_id in card.source_ids}
    assert cited <= set(sources), sorted(cited - set(sources))
    assert cited == set(sources), sorted(set(sources) - cited)


def test_no_card_cites_nothing():
    cards, _ = read_pack()
    assert [card.id for card in cards if not card.source_ids] == []


def test_every_external_source_carries_a_url_and_a_retrieval_record():
    sources = knowledge_check.load_sources(PACK / "sources.yaml")
    for source_id, entry in sources.items():
        if entry.get("evidence_class") == knowledge_check.LOCAL_EVIDENCE_CLASS:
            continue
        assert entry.get("url"), f"{source_id} has no url"
        assert entry.get("retrieved_via"), f"{source_id} does not say how it was read"
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(entry.get("retrieved", ""))), (
            f"{source_id} has no retrieval date"
        )
        assert len(str(entry.get("takeaway", "")).split()) >= 8, f"{source_id} takeaway is filler"


def test_a_source_without_a_single_supporting_card_is_an_error(tmp_path):
    # the validator is not decorative: dropping every citation must be reported, not shrugged off
    broken = tmp_path / "knowledge"
    broken.mkdir()
    cards = [
        {"id": "SM-X-001", "title": "t", "category": "model", "claim": "c",
         "source_ids": [], "tags": ["m"], **{f: "x" for f in knowledge_check.REQUIRED_PROSE},
         "priority": 3, "evidence": "paper"}
    ]
    (broken / "cards.jsonl").write_text(
        "\n".join(json.dumps(card) for card in cards), encoding="utf-8"
    )
    shutil.copyfile(PACK / "sources.yaml", broken / "sources.yaml")
    errors = knowledge_check.validate_pack(broken)
    assert any("SM-X-001" in message for message in errors)
    assert any("cited by no card" in message for message in errors)


# ------------------------------------------------- a sound pack, broken one rule at a time
#
# Every rule the validator owns gets one test that breaks exactly that rule. Without them a rule
# could be deleted from knowledge_check and the suite would stay green, which is the failure mode
# a knowledge pack is most likely to drift into: the checks exist, nothing enforces them.

BASE_SOURCE_TEXT = """
- id: smartmem-homepage
  title: SmartMem competition homepage
  url: https://example.org/smartmem
  retrieved_via: web_fetch
  retrieved: "2026-10-03"
  takeaway: >-
    States the lead window, the prediction window and the metric, which is more than eight words
    and enough for a card to lean on.
"""


def base_card() -> dict:
    card = {
        "id": "SM-T-001",
        "title": "A claim that needs a source",
        "category": "model",
        "claim": "Do the thing on the windowed counts.",
        "source_ids": ["smartmem-homepage"],
        "tags": ["temporal"],
        "priority": 3,
        "evidence": "paper",
    }
    card.update({field: "filled in" for field in knowledge_check.REQUIRED_PROSE})
    return card


def make_pack(tmp_path, *, cards=None, sources_text=BASE_SOURCE_TEXT, files=None) -> Path:
    pack = tmp_path / "knowledge"
    pack.mkdir()
    rows = [base_card()] if cards is None else cards
    body = "\n".join(json.dumps(card, ensure_ascii=False) for card in rows)
    if rows:
        (pack / "cards.jsonl").write_text(body + "\n", encoding="utf-8")
    if sources_text is not None:
        (pack / "sources.yaml").write_text(sources_text, encoding="utf-8")
    for name, content in (files or {}).items():
        (pack / name).write_text(content, encoding="utf-8")
    return pack


def validate_one_card(tmp_path, **overrides) -> list[str]:
    card = base_card()
    card.update(overrides)
    return knowledge_check.validate_pack(make_pack(tmp_path, cards=[card]))


def test_an_id_outside_the_namespace_is_rejected(tmp_path):
    assert any("must start with SM-" in m for m in validate_one_card(tmp_path, id="FE42"))


def test_an_unknown_evidence_class_is_rejected(tmp_path):
    errors = validate_one_card(tmp_path, evidence="team_memory")
    assert any("unknown evidence class" in m for m in errors)


def test_an_empty_risk_field_is_rejected(tmp_path):
    assert any("risk is empty" in m for m in validate_one_card(tmp_path, risk=""))


def test_a_card_that_cites_nothing_is_rejected(tmp_path):
    assert any("cites no source" in m for m in validate_one_card(tmp_path, source_ids=[]))


def test_a_card_that_cites_an_unknown_source_is_rejected(tmp_path):
    errors = validate_one_card(tmp_path, source_ids=["smartmem-never-published"])
    assert any("unknown source smartmem-never-published" in m for m in errors)


def test_a_card_with_no_tags_is_rejected(tmp_path):
    # an untagged card can never be retrieved, so it is dead weight that reads like coverage
    assert any("no tags" in m for m in validate_one_card(tmp_path, tags=[]))


def test_a_missing_sources_file_is_rejected(tmp_path):
    errors = knowledge_check.validate_pack(make_pack(tmp_path, sources_text=None))
    assert any("sources.yaml is missing" in m for m in errors)


def test_a_missing_cards_file_is_rejected(tmp_path):
    errors = knowledge_check.validate_pack(make_pack(tmp_path, cards=[]))
    assert any("cards.jsonl is missing" in m for m in errors)


def test_a_loader_rejection_is_reported_and_stops_the_semantic_pass(tmp_path):
    # the loader refuses an unknown category; the validator must not then pile on bogus findings
    # about a card it never accepted
    errors = validate_one_card(tmp_path, category="vibes")
    assert len(errors) == 1, errors
    assert "category" in errors[0]


def test_an_external_source_missing_a_url_is_rejected(tmp_path):
    text = BASE_SOURCE_TEXT.replace("  url: https://example.org/smartmem\n", "")
    errors = knowledge_check.validate_pack(make_pack(tmp_path, sources_text=text))
    assert any("no url" in m for m in errors)


def test_an_external_source_missing_how_it_was_read_is_rejected(tmp_path):
    text = BASE_SOURCE_TEXT.replace("  retrieved_via: web_fetch\n", "")
    errors = knowledge_check.validate_pack(make_pack(tmp_path, sources_text=text))
    assert any("does not say how it was read" in m for m in errors)


def test_an_external_source_missing_a_retrieval_date_is_rejected(tmp_path):
    text = BASE_SOURCE_TEXT.replace('  retrieved: "2026-10-03"\n', "")
    errors = knowledge_check.validate_pack(make_pack(tmp_path, sources_text=text))
    assert any("no retrieval date" in m for m in errors)


def test_an_external_source_with_a_filler_takeaway_is_rejected(tmp_path):
    text = BASE_SOURCE_TEXT.split("  takeaway: >-")[0] + "  takeaway: it exists\n"
    errors = knowledge_check.validate_pack(make_pack(tmp_path, sources_text=text))
    assert any("takeaway is filler" in m for m in errors)


def test_a_local_source_must_name_the_record_that_holds_it(tmp_path):
    text = BASE_SOURCE_TEXT + "  evidence_class: local\n"
    errors = knowledge_check.validate_pack(make_pack(tmp_path, sources_text=text))
    assert any("local but names no record" in m for m in errors)


def test_a_valid_pack_produces_no_errors_through_the_same_helper(tmp_path):
    # the negative tests above are only meaningful if the untouched baseline really is clean
    assert knowledge_check.validate_pack(make_pack(tmp_path)) == []


# ------------------------------------------------------------------- what may not be shared


def test_no_private_path_or_serial_number_appears_in_the_pack():
    for name in ("cards.jsonl", "sources.yaml", "expert.md", "README.md"):
        text = (PACK / name).read_text(encoding="utf-8")
        assert not re.search(r"[A-Za-z]:[\\/]{1,2}Users[\\/]", text), name
        assert not re.search(r"/home/[a-z0-9_]+/", text), name
        # an unannotated 9+ digit run in a shared file is a serial number or an epoch, either way
        # it identifies a machine the plan says must stay anonymous
        assert re.search(r"\b\d{9,}\b", text) is None, f"{name} carries a bare long number"


def test_a_private_path_inside_a_card_is_an_error(tmp_path):
    errors = validate_one_card(tmp_path, impl_hint="see C:/Users/somebody/raw_tmp for the data")
    assert any("private local path" in m for m in errors)


def test_a_bare_long_number_inside_a_card_is_an_error(tmp_path):
    # the shape of a serial number, which is exactly what the anonymiser exists to remove
    errors = validate_one_card(tmp_path, claim="unit 20261003019 went down after the burst.")
    assert any("bare long number" in m for m in errors)


def test_a_hdd_token_inside_a_card_is_an_error(tmp_path):
    errors = validate_one_card(tmp_path, claim="Watch the reallocated sector count.")
    assert any("HDD token" in m for m in errors)


def test_a_leaked_path_in_the_expert_notes_is_an_error(tmp_path):
    pack = make_pack(tmp_path, files={"expert.md": "Data lives in /home/worker/raw_tmp/.\n"})
    assert any("private local path" in m for m in knowledge_check.validate_pack(pack))


def test_an_unsound_pack_injects_no_cards(tmp_path):
    # load_pack is what a run calls: a pack with problems must give the engine nothing rather than
    # quietly feeding it the cards that did pass
    card = base_card()
    card["risk"] = ""
    pack = make_pack(tmp_path, cards=[card])
    assert knowledge_check.validate_pack(pack)
    cards, errors = knowledge_check.load_pack(pack)
    assert cards == []
    assert any("risk is empty" in message for message in errors)


def test_the_pack_is_not_a_renamed_hdd_pack():
    # section 8.1 forbids carrying SMART counter semantics over to DRAM by swapping nouns; the
    # tokens are matched as words because "headline score" is prose, not a SMART attribute
    text = (PACK / "cards.jsonl").read_text(encoding="utf-8").lower()
    for token in ("smart_5", "smart_187", "197", "reallocated", "power_on_hours", "head"):
        assert re.search(rf"\b{token}\b", text) is None, token


def test_the_knowledge_readme_states_what_the_local_evaluator_cannot_do():
    # the pack is what a reviewer reads first, so it has to state what it cannot do: a local scorer
    # exists since 2026-10-04, and the limit worth recording is that its rules are provisional, so
    # the negation this test pins is "the official spec is not confirmed", in either language
    readme = (PACK / "README.md").read_text(encoding="utf-8").lower()
    assert "evaluator" in readme
    assert re.search(r"\bnot\b|没有|尚未|还不", readme), "the readme claims no limits"
    assert re.search(r"provisional|暂定", readme), "the readme must mark the local spec provisional"


# ------------------------------------------------------------------- retrieval


def test_smartmem_keywords_retrieve_smartmem_cards():
    cards, _ = read_pack()
    retriever = CardRetriever(cards, max_per_category=2, default_k=4)
    picked = retriever.retrieve(
        RetrievalContext(keywords=["temporal", "window", "burst", "parity", "dq"]), k=4
    )
    assert picked, "the pack answers no SmartMem keyword"
    assert all(card.id.startswith("SM-") for card in picked)
    tags = {tag for card in picked for tag in card.tags}
    assert tags & {"parity", "dq", "burst", "temporal", "window"}


def test_hdd_keywords_do_not_lift_a_smartmem_card():
    cards, _ = read_pack()
    smart_only = {"smart", "reallocated", "sectors", "power_on_hours", "spin"}
    hits = [card.id for card in cards if compute_tag_match_score(card, smart_only) > 0.0]
    assert hits == []


def test_loading_only_this_pack_is_enough_for_retrieval():
    # the engine loads a directory, so the pack must be self-contained: no shared default card set
    cards, errors = knowledge_check.load_pack(PACK)
    assert errors == []
    assert cards and all(card.id.startswith("SM-") for card in cards)


# ------------------------------------------------------------------- configuration


def test_evolve_yaml_points_at_the_pack_and_keeps_smoke_off():
    config = yaml.safe_load(
        (PACK.parent / "evolve.yaml").read_text(encoding="utf-8")
    )
    knowledge = config["knowledge"]
    assert knowledge["enabled"] is True
    assert Path(knowledge["dir"]).is_absolute() is False
    assert knowledge["k"] == 4
    assert knowledge["max_per_category"] == 2
    assert config["smoke_test"]["enabled"] is False


def test_the_generic_layers_still_do_not_mention_this_domain():
    # the pack is domain data; the moment a domain word lands in src/faultevolve/data the generic
    # pipeline stops being reusable, which is the rule the whole phase is built on
    for path in Path("src/faultevolve/data").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"\b(DIMM|mcelog|ECC|UE|bankid|SmartMem|smartmem)\b", text), path.name
