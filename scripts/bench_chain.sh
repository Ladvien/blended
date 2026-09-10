#!/bin/zsh
# One benchmark roll, end to end, the only order that yields a rankable
# number (OT-21): sweep -> bake -> score -> diagnose. The scorers run
# only if the bake left every instance with its render log and GLB.
#
#   WORKTREE=/Users/ladvien/blended-bench MODEL_DIR=blended-deepseek-v4-pro-ops-roll1 \
#   WRITER=deepseek-v4-pro:cloud EYE=kimi-k2.7-code:cloud \
#   scripts/bench_chain.sh
#
# WORKTREE is a FROZEN checkout (git worktree) so the main tree can move
# while a roll runs; the diagnose json lands in the main tree's
# outputs/bench/ for bench_panel.py.
set -u
: ${WORKTREE:?frozen worktree path}
: ${MODEL_DIR:?results/text_to_3D_agent/<dir>}
: ${WRITER:?writer model id}
: ${EYE:=}
: ${BENCH_ROOT:=/Users/ladvien/3dcodebench}
: ${INSTANCES:=$WORKTREE/bench_sets/instances_holdout.txt}
: ${OUT:=/Users/ladvien/blended/outputs/bench}
: ${TIMEOUT:=1500}
L=$OUT/logs; mkdir -p $L
RESULTS=$BENCH_ROOT/results/text_to_3D_agent
say() { echo "[chain] $MODEL_DIR $1 $(date)" >> $L/chain_$MODEL_DIR.log; }

say "sweep start"
EYE_ARGS=(); [ -n "$EYE" ] && EYE_ARGS=(--vision-model "$EYE")
$WORKTREE/.venv/bin/python $WORKTREE/scripts/sweep_3dcode.py --bench-root $BENCH_ROOT \
  --instances-file $INSTANCES --model "$WRITER" "${EYE_ARGS[@]}" --timeout $TIMEOUT \
  --model-dir $MODEL_DIR > $L/${MODEL_DIR}_sweep.log 2>&1
say "sweep exit $?"

$WORKTREE/.venv/bin/python $WORKTREE/scripts/bake_3dcode.py --bench-root $BENCH_ROOT \
  --model-dir $MODEL_DIR > $L/${MODEL_DIR}_bake.log 2>&1
BAKE=$?
say "bake exit $BAKE"
if [ $BAKE -ne 0 ]; then say "NOT SCORED: bake left artifacts missing"; exit $BAKE; fi

(cd $BENCH_ROOT && .venv/bin/python metrics/executability.py --model $MODEL_DIR --results-root $RESULTS > $L/${MODEL_DIR}_exec.log 2>&1)
(cd $BENCH_ROOT && .venv/bin/python metrics/shape_chamfer.py --model $MODEL_DIR --results-root $RESULTS > $L/${MODEL_DIR}_chamfer.log 2>&1)
(cd $WORKTREE && $BENCH_ROOT/.venv/bin/python scripts/diagnose_3dcode.py --bench-root $BENCH_ROOT --model-dir $MODEL_DIR \
  --instances-file $INSTANCES --out $OUT/diagnose_$MODEL_DIR.md --json $OUT/diagnose_$MODEL_DIR.json > $L/${MODEL_DIR}_diagnose.log 2>&1)
say "scored exit $?"
