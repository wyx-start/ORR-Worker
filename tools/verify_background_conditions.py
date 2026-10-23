"""Run checks in a detached copy with public synthetic examples and no presets.

No real example TXT, user_settings, credentials or active Streamlit service is
read by this runner. Logs and a machine-readable result remain in verification/.
"""
from pathlib import Path
import argparse
import datetime
import json
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]

WORKER = '''
import json
import logging
import pathlib
import sys
import unittest
root = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(root))
sys.path.insert(1, str(root / "tests"))
logging.getLogger("streamlit").setLevel(logging.ERROR)
import experiment_conditions
experiment_conditions.PROFILE_PATH = root / "user_settings" / "isolated_presets.json"
loader = unittest.TestLoader()
suite = unittest.TestSuite()
modules = json.loads(sys.argv[1])
if modules:
    for module in modules:
        suite.addTests(loader.loadTestsFromName(module))
else:
    suite.addTests(loader.discover(str(root / "tests"), pattern="test_*.py"))
result = unittest.TextTestRunner(verbosity=2).run(suite)
payload = {"tests_run": result.testsRun, "failures": [{"test": str(t), "traceback": message} for t, message in result.failures],
           "errors": [{"test": str(t), "traceback": message} for t, message in result.errors],
           "skipped": [{"test": str(t), "reason": reason} for t, reason in result.skipped],
           "successful": result.wasSuccessful()}
pathlib.Path(sys.argv[2]).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
sys.exit(0 if result.wasSuccessful() else 1)
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module", action="append", default=[], help="Unittest module name; default: all tests")
    args = parser.parse_args()
    destination = ROOT / "verification"
    destination.mkdir(exist_ok=True)
    isolation = Path(tempfile.mkdtemp(prefix="background_conditions_", dir=destination))
    for path in ROOT.iterdir():
        if path.is_file() and (path.suffix in (".py", ".cmd", ".md") or path.name == "requirements.txt"):
            shutil.copy2(path, isolation / path.name)
    for folder in ("tests", "app_pages", ".streamlit", "tools"):
        for source in (ROOT / folder).rglob("*"):
            if folder == ".streamlit" and source.name != "config.toml":
                continue
            if source.is_file() and source.suffix in (".py", ".cjs", ".toml"):
                target = isolation / source.relative_to(ROOT)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
    synthetic = isolation / "examples"
    # Generate into the fresh copy. A public checkout has no private .release/
    # directory, and its root examples must never be trusted as experimental-free.
    subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "tools" / "generate_demo_data.py"),
                    "--output", str(synthetic)], cwd=ROOT, check=True, capture_output=True)
    worker = isolation / "run_isolated_checks.py"
    worker.write_text(WORKER, encoding="utf-8")
    report = isolation / "result.json"
    log = isolation / "checks.log"
    started = datetime.datetime.now(datetime.timezone.utc)
    with log.open("w", encoding="utf-8") as stream:
        completed = subprocess.run([sys.executable, "-X", "utf8", str(worker), json.dumps(args.module), str(report)],
                                   cwd=isolation, stdout=stream, stderr=subprocess.STDOUT)
    data = json.loads(report.read_text(encoding="utf-8")) if report.exists() else {
        "successful": False, "tests_run": 0, "errors": [{"test": "runner", "traceback": "See log"}], "failures": []}
    data.update(started_utc=started.isoformat(), duration_seconds=(datetime.datetime.now(datetime.timezone.utc)-started).total_seconds(),
                modules=args.module, isolation=str(isolation), log=str(log), synthetic_examples=str(synthetic),
                source_root=str(ROOT), real_samples_read=False, real_presets_read=False)
    report.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(report), "successful": data["successful"], "tests_run": data["tests_run"],
                      "failures": [item["test"] for item in data["failures"]],
                      "errors": [item["test"] for item in data["errors"]],
                      "duration_seconds": data["duration_seconds"]}, ensure_ascii=False))
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
