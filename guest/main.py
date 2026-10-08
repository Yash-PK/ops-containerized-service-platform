"""Guest-only explicit lab phases, with structured reports and cleanup outcomes."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from guest import prepare, scenario  # noqa: E402
from guest.common import LAB_ID, ROOT, Context  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("prepare", "run"))
    parser.add_argument("--lab-id", required=True)
    parser.add_argument("--confirm", required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if args.lab_id != LAB_ID or args.confirm != LAB_ID or not args.execute:
        parser.error("Exact lab ID, confirmation and execution required")
    ctx = Context()
    passed = False
    try:
        if args.phase == "prepare":
            ctx.report["expected_kernel"] = prepare.run(ctx)
        else:
            scenario.execute(ctx)
        passed = True
    except Exception as error:
        ctx.report["error"] = str(error)[:300]
        ctx.report["error_type"] = type(error).__name__
        if args.phase == "run" and (ROOT / "engine-owner.json").exists():
            try:
                scenario.engine.owned(ctx)
                output = ctx.compose(
                    ["logs", "--no-color", "--tail", "30"], label="failure-diagnostics"
                )
                ctx.report.setdefault("private_diagnostics", []).append(
                    {"label": "service-logs", "output": output[-48000:]}
                )
            except Exception:
                pass
    finally:
        if args.phase == "run":
            try:
                scenario.cleanup(ctx)
                ctx.report["cleanup"] = "passed"
            except Exception as error:
                ctx.report["cleanup"] = "failed"
                ctx.report["cleanup_error"] = str(error)[:300]
                passed = False
    ctx.report["passed"] = passed
    print(json.dumps(ctx.report))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
