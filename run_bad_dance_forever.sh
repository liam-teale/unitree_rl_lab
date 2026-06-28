#!/usr/bin/env bash
# Supervisor: keep mimic training for `bad_dance` running until explicitly stopped.
# Stop gracefully with:  touch /home/liam-teale/unitree_rl_lab/.stop_bad_dance
# (the current training finishes its step and the loop exits instead of restarting)
source /home/liam-teale/miniconda3/etc/profile.d/conda.sh
conda activate unitree_sim_env
cd /home/liam-teale/unitree_rl_lab || exit 1

STOP_FILE="/home/liam-teale/unitree_rl_lab/.stop_bad_dance"
LOG="logs/train_bad_dance_console.log"
rm -f "$STOP_FILE"

attempt=0
while [ ! -f "$STOP_FILE" ]; do
    attempt=$((attempt + 1))
    echo "[supervisor] launch #$attempt at $(date '+%F %T')" | tee -a "$LOG"
    # --resume with no --load_run => loads the latest run's latest checkpoint.
    # First launch resumes from run 2026-06-26_20-18-20 (model_4500); later
    # launches chain from whichever run was most recent.
    python scripts/rsl_rl/train.py \
        --task Unitree-G1-29dof-Mimic-Bad-Dance \
        --headless \
        --num_envs 2048 \
        --max_iterations 1000000 \
        --resume \
        2>&1 | tee -a "$LOG"
    status=${PIPESTATUS[0]}
    echo "[supervisor] training exited status=$status at $(date '+%F %T')" | tee -a "$LOG"

    if [ -f "$STOP_FILE" ]; then
        echo "[supervisor] stop file found -> exiting" | tee -a "$LOG"
        break
    fi
    echo "[supervisor] restarting in 10s ... (touch $STOP_FILE to stop)" | tee -a "$LOG"
    sleep 10
done

rm -f "$STOP_FILE"
echo "[supervisor] stopped." | tee -a "$LOG"
