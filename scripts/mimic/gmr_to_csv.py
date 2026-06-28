"""Convert a GMR (General Motion Retargeting) G1 motion into the CSV format
consumed by ``scripts/mimic/csv_to_npz.py``.

The target CSV has one row per frame, no header, 36 comma-separated columns:
    [root_x, root_y, root_z,  qx, qy, qz, qw,  joint_0 ... joint_28]
- root position in meters (world frame)
- root quaternion in xyzw order
- 29 joint angles in radians, in Unitree G1 SDK joint order

GMR already saves root_rot as xyzw and its G1 dof order matches the Unitree
SDK order, so this is a pure concatenation -- no quaternion reorder, no joint
remap. (GMR also ships scripts/batch_gmr_pkl_to_csv.py which does the same for
a whole folder.)

.. code-block:: bash

    python scripts/mimic/gmr_to_csv.py -i motion.pkl -o motion.bvh_60hz.csv
    # then:
    python scripts/mimic/csv_to_npz.py -f motion.bvh_60hz.csv --input_fps 30
"""

import argparse
import pickle

import numpy as np

# Unitree G1 29-dof SDK joint order (must match joint_sdk_names in
# source/unitree_rl_lab/unitree_rl_lab/assets/robots/unitree.py).
SDK_JOINT_ORDER = [
    "left_hip_pitch_joint", "left_hip_roll_joint", "left_hip_yaw_joint",
    "left_knee_joint", "left_ankle_pitch_joint", "left_ankle_roll_joint",
    "right_hip_pitch_joint", "right_hip_roll_joint", "right_hip_yaw_joint",
    "right_knee_joint", "right_ankle_pitch_joint", "right_ankle_roll_joint",
    "waist_yaw_joint", "waist_roll_joint", "waist_pitch_joint",
    "left_shoulder_pitch_joint", "left_shoulder_roll_joint", "left_shoulder_yaw_joint",
    "left_elbow_joint", "left_wrist_roll_joint", "left_wrist_pitch_joint",
    "left_wrist_yaw_joint", "right_shoulder_pitch_joint", "right_shoulder_roll_joint",
    "right_shoulder_yaw_joint", "right_elbow_joint", "right_wrist_roll_joint",
    "right_wrist_pitch_joint", "right_wrist_yaw_joint",
]


def load_gmr(path):
    """Load a GMR motion file (.pkl or .npz) into a dict of arrays."""
    if path.endswith(".npz"):
        return dict(np.load(path, allow_pickle=True))
    with open(path, "rb") as f:
        data = pickle.load(f)
    return data


def extract_qpos(data):
    """Pull (root_pos, root_quat_wxyz, dof) out of a GMR motion dict.

    GMR builds the robot state as MuJoCo qpos. Different GMR versions save it
    either as a single ``qpos`` array or as split ``root_pos`` / ``root_rot`` /
    ``dof_pos`` keys. Handle both; print what was found so it can be verified.
    """
    print(f"[info] keys: {list(data.keys())}")

    if "qpos" in data:
        qpos = np.asarray(data["qpos"], dtype=np.float64)
        root_pos = qpos[:, 0:3]
        root_quat = qpos[:, 3:7]   # MuJoCo free joint: wxyz
        dof = qpos[:, 7:]
    else:
        # split-key layout
        root_pos = np.asarray(data["root_pos"], dtype=np.float64)
        root_quat = np.asarray(data["root_rot"], dtype=np.float64)
        dof_key = "dof_pos" if "dof_pos" in data else "joint_pos"
        dof = np.asarray(data[dof_key], dtype=np.float64)

    print(f"[info] frames={root_pos.shape[0]} dof={dof.shape[1]}")
    if dof.shape[1] != len(SDK_JOINT_ORDER):
        raise ValueError(
            f"expected {len(SDK_JOINT_ORDER)} dof, got {dof.shape[1]}. "
            "Check that this is a G1 29-dof retarget."
        )
    return root_pos, root_quat, dof


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("-i", "--input", required=True, help="GMR motion file (.pkl or .npz)")
    p.add_argument("-o", "--output", required=True, help="output .csv path")
    p.add_argument(
        "--quat_order", choices=["wxyz", "xyzw"], default="xyzw",
        help="quaternion order of root_rot in the GMR file. GMR saves xyzw. Default: xyzw",
    )
    p.add_argument(
        "--joint_names", nargs="*", default=None,
        help=(
            "GMR joint names in their stored order. If given, columns are "
            "remapped to SDK order. Omit if GMR already uses SDK order."
        ),
    )
    args = p.parse_args()

    data = load_gmr(args.input)
    root_pos, root_quat, dof = extract_qpos(data)

    # quaternion -> xyzw
    if args.quat_order == "wxyz":
        root_quat = root_quat[:, [1, 2, 3, 0]]

    # optional joint remap to SDK order
    if args.joint_names:
        if len(args.joint_names) != dof.shape[1]:
            raise ValueError("--joint_names length must match dof count")
        idx = [args.joint_names.index(n) for n in SDK_JOINT_ORDER]
        dof = dof[:, idx]
        print("[info] remapped joints to SDK order")

    out = np.concatenate([root_pos, root_quat, dof], axis=1)
    assert out.shape[1] == 36, out.shape
    np.savetxt(args.output, out, delimiter=",", fmt="%.6f")
    print(f"[info] wrote {out.shape[0]} frames x {out.shape[1]} cols -> {args.output}")


if __name__ == "__main__":
    main()
