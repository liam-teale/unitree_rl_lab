#!/usr/bin/env python3
"""
Release the G1's onboard high-level motion-control service so a custom low-level
controller (g1_ctrl) can take over the rt/lowcmd channel.

No-compile equivalent of the C++ SDK example
(unitree_sdk2/example/g1/low_level/g1_ankle_swing_example.cpp): calls the
MotionSwitcher service's ReleaseMode() until no high-level mode is active, then
LOUDLY reports whether the onboard controller is ONLINE (dangerous) or OFFLINE
(safe to take over).

Usage:
    python release_onboard_control.py [network_interface]   # default: enp6s0

Exit code 0 = OFFLINE/safe, 1 = still ONLINE or comms error -> do NOT start g1_ctrl.
"""
import sys
import time

from unitree_sdk2py.core.channel import ChannelFactoryInitialize, ChannelSubscriber
from unitree_sdk2py.comm.motion_switcher.motion_switcher_client import (
    MotionSwitcherClient,
)
from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowCmd_

DOMAIN_ID = 0          # must match g1_ctrl: ChannelFactory Init(0, ...)
LOWCMD_WINDOW_S = 0.6  # how long to sniff rt/lowcmd for stray traffic

# ---- ANSI colors ----
R = "\033[1;37;41m"   # white on red
G = "\033[1;30;42m"   # black on green
Y = "\033[1;30;43m"   # black on yellow
C = "\033[1;36m"      # cyan
Z = "\033[0m"         # reset
BELL = "\a"


def banner(color: str, lines) -> None:
    width = 70
    print(BELL + color + " " * width + Z)
    for ln in lines:
        print(color + "  " + ln.ljust(width - 2) + Z)
    print(color + " " * width + Z + "\n")


def query_mode(msc) -> tuple:
    """Return (ok, name). ok=False means the service didn't answer."""
    code, result = msc.CheckMode()
    if code != 0:
        return False, None
    return True, (result or {}).get("name", "")


def lowcmd_message_count(window_s: float) -> int:
    """Directly sniff rt/lowcmd and count messages over `window_s`.

    0 messages => nobody is commanding the motors (onboard controller released
    AND no stray g1_ctrl/low-level program is publishing). Anything > 0 means
    something still owns the channel.
    """
    count = {"n": 0}

    def _on(_msg):
        count["n"] += 1

    sub = ChannelSubscriber("rt/lowcmd", LowCmd_)
    sub.Init(_on, 10)
    time.sleep(window_s)
    try:
        sub.Close()
    except Exception:
        pass
    return count["n"]


def main() -> int:
    iface = sys.argv[1] if len(sys.argv) > 1 else "enp6s0"
    print(f"{C}[release] DDS domain {DOMAIN_ID}, interface '{iface}'{Z}")
    ChannelFactoryInitialize(DOMAIN_ID, iface)

    msc = MotionSwitcherClient()
    msc.SetTimeout(5.0)
    msc.Init()

    # --- initial state ---
    ok, name = query_mode(msc)
    if not ok:
        banner(R, [
            "CANNOT REACH THE MOTION-SWITCHER SERVICE.",
            f"No answer on interface '{iface}', DDS domain {DOMAIN_ID}.",
            "Check: cable/switch, interface name, robot powered & booted,",
            "multicast passing the switch. DO NOT START g1_ctrl.",
        ])
        return 1
    if name:
        banner(Y, [f"ONBOARD CONTROLLER IS CURRENTLY *ONLINE*  (mode: '{name}')",
                   "Robot must be on the hoist/supported -- releasing now..."])
    else:
        print(f"{C}[release] No active high-level mode at start.{Z}")

    # --- release loop ---
    for attempt in range(1, 13):  # ~1 min worst case
        ok, name = query_mode(msc)
        if not ok:
            print(f"{Y}[release] CheckMode no-reply (attempt {attempt}), retrying...{Z}")
            time.sleep(2.0)
            continue
        if not name:
            break
        print(f"{C}[release] active mode '{name}' (attempt {attempt}) -> ReleaseMode(){Z}")
        msc.ReleaseMode()
        time.sleep(5.0)

    # --- FINAL VERIFICATION ---
    # (1) CONTROL PLANE: MotionSwitcher reports no active mode, stable across 3 checks
    last_name = None
    for _ in range(3):
        ok, name = query_mode(msc)
        if not ok:
            banner(R, ["LOST CONTACT WITH MOTION-SWITCHER DURING VERIFICATION.",
                       "State UNKNOWN. DO NOT START g1_ctrl."])
            return 1
        last_name = name
        if name:
            banner(R, ["##############  ONBOARD CONTROLLER: STILL ONLINE  ##############",
                       f"Active mode: '{last_name}'.  Release did NOT take.",
                       "DO NOT START g1_ctrl -- it would fight the onboard controller.",
                       "Try the remote (L2+R2 damping/debug) or re-run this script."])
            return 1
        time.sleep(0.5)

    # (2) DATA PLANE: confirm NOTHING is actually publishing rt/lowcmd
    print(f"{C}[release] mode clear; sniffing rt/lowcmd for {LOWCMD_WINDOW_S:.1f}s ...{Z}")
    n = lowcmd_message_count(LOWCMD_WINDOW_S)
    if n > 0:
        banner(R, ["##########  SOMETHING IS PUBLISHING rt/lowcmd  ##########",
                   f"Saw {n} lowcmd msg(s) in {LOWCMD_WINDOW_S:.1f}s with no active mode.",
                   "Likely a leftover g1_ctrl or another low-level program.",
                   "DO NOT START g1_ctrl. Kill the other publisher first."])
        return 1

    banner(G, ["================  ONBOARD CONTROLLER: OFFLINE  ================",
               "No active mode (verified 3x) AND rt/lowcmd is silent (0 msgs).",
               "lowcmd channel is FREE. Safe to start g1_ctrl now."])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
