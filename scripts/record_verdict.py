"""Append an examiner's verdict for one iteration.

Measurements come from the driver; judgements come from whoever looked
at the render. They live in separate append-only files so a judgement
recorded later never rewrites a measurement taken earlier.

    .venv/bin/python scripts/record_verdict.py \\
        --iteration 2 --brief planter_box --inspected \\
        --deviation "never terminated: exhausted 16 tool calls" \\
        --classification prompt \\
        --hypothesis "..." --prompt-change "v1 -> v2: terminal state"
"""

import argparse
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from blended.evaluate.iteration_log import (  # noqa: E402
    DEFAULT_VERDICT_PATH,
    IterationVerdict,
    VerdictLog,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iteration", type=int, required=True)
    parser.add_argument("--brief", required=True)
    parser.add_argument("--inspected", action="store_true")
    parser.add_argument("--deviation", action="append", default=[])
    parser.add_argument("--classification", default="")
    parser.add_argument("--hypothesis", default="")
    parser.add_argument("--prompt-change", default="")
    parser.add_argument("--notes", default="")
    parser.add_argument("--path", default=str(DEFAULT_VERDICT_PATH))
    arguments = parser.parse_args()

    verdict = IterationVerdict(
        iteration=arguments.iteration,
        brief_name=arguments.brief,
        visual_inspected=arguments.inspected,
        visual_deviations=tuple(arguments.deviation),
        classification=arguments.classification,
        hypothesis=arguments.hypothesis,
        prompt_change=arguments.prompt_change,
        notes=arguments.notes,
    )
    VerdictLog(Path(arguments.path)).append(verdict)
    print(
        f"recorded verdict: iteration {verdict.iteration} {verdict.brief_name} "
        f"inspected={verdict.visual_inspected} "
        f"deviations={len(verdict.visual_deviations)} "
        f"classification={verdict.classification or '(none)'}"
    )
    return 0


raise SystemExit(main())
