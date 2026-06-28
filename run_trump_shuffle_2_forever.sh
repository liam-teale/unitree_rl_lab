#!/usr/bin/env bash
# Supervisor: keep mimic training for `trump_shuffle_2` running overnight until done.
# Fast-finish, unattended run. Auto-resumes from the latest checkpoint after any crash
# (OOM, segfault, etc.) so a 4 AM failure doesn't waste the night.
#
# Stop gracefully with:  touch /home/liam-teale/unitree_rl_lab/.stop_trump_shuffle_2
#   (the current training finishes its step and the loop exits instead of restarting)
set -uo pipefail
source /home/liam-teale/miniconda3/etc/profile.d/conda.sh
conda activate unitree_sim_env
cd /home/liam-teale/unitree_rl_lab || exit 1

STOP_FILE="/home/liam-teale/unitree_rl_lab/.stop_trump_shuffle_2"
LOG="logs/train_trump_shuffle_2_console.log"
NUM_ENVS="${NUM_ENVS:-8192}"
rm -f "$STOP_FILE"

attempt=0
while [ ! -f "$STOP_FILE" ]; do
    attempt=$((attempt + 1))
    # First launch: fresh run. Later launches (after a crash): --resume picks up the
    # most recent run's latest checkpoint automatically.
    if [ "$attempt" -eq 1 ]; then RESUME=""; else RESUME="--resume"; fi
    echo "[supervisor] launch #$attempt (envs=$NUM_ENVS resume='${RESUME}') at $(date '+%F %T')" | tee -a "$LOG"

    python -u scripts/rsl_rl/train.py \
        --task=Unitree-G1-29dof-Mimic-Trump-Shuffle-2 \
        --headless \
        --num_envs "$NUM_ENVS" \
        --max_iterations 60000 \
        $RESUME \
        2>&1 | tee -a "$LOG"
    status=${PIPESTATUS[0]}
    echo "[supervisor] training exited status=$status at $(date '+%F %T')" | tee -a "$LOG"

    if [ -f "$STOP_FILE" ]; then
        echo "[supervisor] stop file found -> exiting" | tee -a "$LOG"
        break
    fi
    # status 0 = reached max_iterations (done). Don't restart.
    if [ "$status" -eq 0 ]; then
        echo "[supervisor] training completed cleanly (max_iterations) -> exiting" | tee -a "$LOG"
        break
    fi
    echo "[supervisor] crash (status=$status); restarting in 10s with --resume ... (touch $STOP_FILE to stop)" | tee -a "$LOG"
    sleep 10
done

rm -f "$STOP_FILE"
echo "[supervisor] stopped at $(date '+%F %T')." | tee -a "$LOG"
