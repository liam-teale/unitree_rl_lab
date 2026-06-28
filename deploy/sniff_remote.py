#!/usr/bin/env python3
"""Sniff rt/lowstate and show the 40-byte wireless_remote payload live.

If the bytes change when you press buttons on the remote -> it's paired and
g1_ctrl will see it. If they stay all-zero -> the remote is NOT reaching the
robot's LowState (pairing/power issue), regardless of g1_ctrl.

Usage: python sniff_remote.py [iface]   (default enp6s0)
"""
import sys, time
from unitree_sdk2py.core.channel import ChannelFactoryInitialize, ChannelSubscriber
from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowState_

iface = sys.argv[1] if len(sys.argv) > 1 else "enp6s0"
ChannelFactoryInitialize(0, iface)

state = {"n": 0, "last": None, "nonzero_seen": False}

def on(msg: LowState_):
    state["n"] += 1
    wr = bytes(msg.wireless_remote)
    nz = any(wr)
    if nz:
        state["nonzero_seen"] = True
    if wr != state["last"]:
        state["last"] = wr
        tag = "NONZERO/CHANGED" if nz else "all-zero"
        print(f"[{state['n']:5d}] {tag}: {wr.hex()}")

sub = ChannelSubscriber("rt/lowstate", LowState_)
sub.Init(on, 10)

print(f"Listening on rt/lowstate ({iface}). Press remote buttons now. Ctrl-C to stop.\n")
try:
    while True:
        time.sleep(1.0)
        if state["n"] == 0:
            print("  ...no LowState messages at all -> robot not publishing / not reachable.")
except KeyboardInterrupt:
    pass

print(f"\nTotal LowState msgs: {state['n']}, any nonzero remote bytes seen: {state['nonzero_seen']}")
