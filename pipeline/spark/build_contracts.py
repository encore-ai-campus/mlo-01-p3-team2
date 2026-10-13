import argparse
import json
from pathlib import Path

from spark_pipeline.contracts import compile_contracts

ROOT = Path(__file__).resolve().parent

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=str(ROOT.parent / "std_and_sinker/contracts"))
    parser.add_argument("--output", default=str(ROOT / "contracts/registry.json"))
    args = parser.parse_args()
    registry = compile_contracts(args.source)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n")
    print(f"{len(registry['schemas'])} schemas, {len(registry['routes'])} routes: {output}")
