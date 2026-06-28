# Copyright (c) 2022-2025, The Isaac Lab Project Developers.
# All rights reserved.
#
# SPDX-License-Identifier: BSD-3-Clause

"""Play an exported ONNX policy in an Isaac Lab RSL-RL environment."""

import argparse
import os
import time

from isaaclab.app import AppLauncher


parser = argparse.ArgumentParser(description="Play an exported ONNX policy.")
parser.add_argument("--onnx", type=str, required=True, help="Path to exported ONNX policy.")
parser.add_argument("--task", type=str, required=True, help="Name of the task.")
parser.add_argument("--video", action="store_true", default=False, help="Record a video.")
parser.add_argument("--video_length", type=int, default=200, help="Length of the recorded video in steps.")
parser.add_argument("--num_envs", type=int, default=None, help="Number of environments to simulate.")
parser.add_argument("--disable_fabric", action="store_true", default=False, help="Disable fabric and use USD I/O.")
parser.add_argument("--real-time", action="store_true", default=False, help="Run in real time, if possible.")
AppLauncher.add_app_launcher_args(parser)
args_cli = parser.parse_args()

if args_cli.video:
    args_cli.enable_cameras = True

app_launcher = AppLauncher(args_cli)
simulation_app = app_launcher.app

import gymnasium as gym
import numpy as np
import onnxruntime as ort
import torch

from isaaclab.envs import DirectMARLEnv, multi_agent_to_single_agent
from isaaclab.utils.dict import print_dict
from isaaclab_rl.rsl_rl import RslRlVecEnvWrapper

import isaaclab_tasks  # noqa: F401
import unitree_rl_lab.tasks  # noqa: F401
from unitree_rl_lab.utils.parser_cfg import parse_env_cfg


def _observations(env):
    obs = env.get_observations()
    return _policy_obs(obs)


def _policy_obs(obs):
    if isinstance(obs, tuple):
        obs = obs[0]
    if hasattr(obs, "keys") and "policy" in obs.keys():
        obs = obs["policy"]
    return obs


def main():
    env_cfg = parse_env_cfg(
        args_cli.task,
        device=args_cli.device,
        num_envs=args_cli.num_envs,
        use_fabric=not args_cli.disable_fabric,
        entry_point_key="play_env_cfg_entry_point",
    )
    env = gym.make(args_cli.task, cfg=env_cfg, render_mode="rgb_array" if args_cli.video else None)

    if isinstance(env.unwrapped, DirectMARLEnv):
        env = multi_agent_to_single_agent(env)

    if args_cli.video:
        video_folder = os.path.join(os.path.dirname(os.path.abspath(args_cli.onnx)), "videos", "onnx_play")
        video_kwargs = {
            "video_folder": video_folder,
            "step_trigger": lambda step: step == 0,
            "video_length": args_cli.video_length,
            "disable_logger": True,
        }
        print("[INFO] Recording videos during ONNX play.")
        print_dict(video_kwargs, nesting=4)
        env = gym.wrappers.RecordVideo(env, **video_kwargs)

    env = RslRlVecEnvWrapper(env)
    session = ort.InferenceSession(os.path.abspath(args_cli.onnx), providers=["CPUExecutionProvider"])
    input_name = session.get_inputs()[0].name
    output_name = session.get_outputs()[0].name

    obs = _observations(env)
    timestep = 0
    dt = env.unwrapped.step_dt

    while simulation_app.is_running():
        start_time = time.time()
        obs = _policy_obs(obs)
        obs_np = obs.detach().cpu().numpy().astype(np.float32)
        actions_np = session.run([output_name], {input_name: obs_np})[0]
        actions = torch.from_numpy(actions_np).to(device=env.unwrapped.device)
        obs, _, _, _ = env.step(actions)
        obs = _policy_obs(obs)

        if args_cli.video:
            timestep += 1
            if timestep == args_cli.video_length:
                break

        sleep_time = dt - (time.time() - start_time)
        if args_cli.real_time and sleep_time > 0:
            time.sleep(sleep_time)

    env.close()


if __name__ == "__main__":
    main()
    simulation_app.close()
