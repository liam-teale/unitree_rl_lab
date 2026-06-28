#!/usr/bin/env bash
set -eo pipefail

source /home/liam-teale/miniconda3/etc/profile.d/conda.sh
conda activate isaaclab_v6
cd /home/liam-teale/unitree_rl_lab

exec python scripts/rsl_rl/train.py \
  --task=Unitree-G1-29dof-Mimic-Bad-Dance \
  --video --video_length 300 --video_interval 2000 \
  --max_iterations 5000 \
  --headless
