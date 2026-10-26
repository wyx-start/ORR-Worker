"""Explicitly freeze generated baseline data; normal tests never update it."""
from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT),str(ROOT/"tests")]
from migration_fixtures import snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    args = parser.parse_args()
    data = snapshot()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open("x",encoding="utf-8") as file:
        json.dump(data,file,ensure_ascii=False,separators=(",",":"),allow_nan=False)
    print(args.output)


if __name__ == "__main__":
    main()
