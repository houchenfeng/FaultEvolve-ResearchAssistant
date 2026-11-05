"""One metered real provider probe; never prints credentials or response bodies."""
import argparse
import importlib.util
import json
from pathlib import Path


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--records", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--env-file", required=True)
    args = parser.parse_args()
    repo, output = Path(args.repo), Path(args.output)
    control = load(repo / "experiments/hdd_dl/controller.py", "probe_controller")
    planner = load(repo / "experiments/hdd_dl/planner.py", "probe_planner")
    control.guard(Path("/home/hcf/nas_hcf_data"), output)
    output.mkdir(parents=True, exist_ok=True)
    records = json.loads(Path(args.records).read_text(encoding="utf-8"))
    knowledge = json.loads((repo / "experiments/hdd_dl/knowledge.json").read_text(encoding="utf-8"))
    parent = control.seed_configs(records)[0]
    proposal = planner.propose(
        trial=0, parent=parent, records=records, knowledge=knowledge, space=control.SPACE,
        ledger_path=output / "planner.json", write_json=control.write_json,
        env_file=args.env_file, max_calls=1)
    print(json.dumps({"accepted": proposal is not None, "changes": proposal.get("changes") if proposal else None}))


if __name__ == "__main__":
    main()
