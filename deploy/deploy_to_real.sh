#!/usr/bin/env bash
# Deploy the G1-29dof policy to the REAL robot.
#
# Does, in order:
#   1. Add the robot's 192.168.123.x address to the wired NIC as a *secondary*
#      address (your DHCP/internet address on that NIC is left untouched).
#   2. Flush the ARP/neighbor cache and confirm the robot answers ping.
#   3. Release the onboard high-level controller so g1_ctrl can own rt/lowcmd
#      (aborts if it can't be released -- never fights the onboard controller).
#   4. Launch g1_ctrl on that interface.
#
# On exit (normal, Ctrl-C, or an aborted safety gate) every network change this
# script made is reverted, so your interface is left exactly as it was found.
#
# Usage:
#   ./deploy_to_real.sh                 # use defaults below (keeps internet up)
#   IFACE=enp7s0 ./deploy_to_real.sh    # override the interface
#   ./deploy_to_real.sh --force         # skip ping/release safety gates (DANGEROUS)
#   ./deploy_to_real.sh --exclusive     # remove other IPv4 addrs (only if DDS
#                                       # multicast misbehaves); restored on exit
#
# After it launches:  L2+Up -> FixStand,  then R1+X -> run policy.
set -uo pipefail

# ---- config (override via env) ----
IFACE="${IFACE:-enp6s0}"
HOST_IP="${HOST_IP:-192.168.123.222/24}"
ROBOT_IP="${ROBOT_IP:-192.168.123.161}"   # robot onboard PC; try .164 if no reply
CONDA_ENV="${CONDA_ENV:-unitree_sim_env}"
SUBNET_PREFIX="192.168.123."

# ---- flags ----
FORCE=0
EXCLUSIVE=0
for arg in "$@"; do
    case "$arg" in
        --force)      FORCE=1 ;;
        --exclusive)  EXCLUSIVE=1 ;;
        --keep-other) : ;;   # deprecated: keeping other addrs is now the default
        -h|--help)    sed -n '2,21p' "$0"; exit 0 ;;
        *) echo "unknown arg: $arg" >&2; exit 2 ;;
    esac
done

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
G1_CTRL="$DEPLOY_DIR/robots/g1_29dof/build/g1_ctrl"

say()  { printf '\033[1;36m[deploy]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;37;41m[deploy] %s\033[0m\n' "$*" >&2; exit 1; }

# ---- sanity ----
[ -x "$G1_CTRL" ] || die "g1_ctrl not found/executable at $G1_CTRL (build it first: cmake .. && make)"
ip link show "$IFACE" >/dev/null 2>&1 || die "interface '$IFACE' does not exist (check: ip -br link)"

# ---- network-change tracking + cleanup ----
# Record exactly what we change so we can undo it on exit. Internet on $IFACE is
# driven by NetworkManager; bringing its active connection back up reapplies the
# original DHCP address + default route after --exclusive mode removed them.
ADDED_HOST_IP=0
REMOVED_ANY=0
CONN="$(nmcli -t -f NAME,DEVICE connection show --active 2>/dev/null \
        | awk -F: -v d="$IFACE" '$2==d{print $1; exit}')"

cleanup() {
    local rc=$?
    trap - EXIT
    say "Restoring network on $IFACE"
    if [ "$ADDED_HOST_IP" -eq 1 ]; then
        sudo ip addr del "$HOST_IP" dev "$IFACE" 2>/dev/null || true
    fi
    if [ "$REMOVED_ANY" -eq 1 ] && [ -n "$CONN" ]; then
        say "Reapplying '$CONN' to restore DHCP address + default route"
        sudo nmcli connection up "$CONN" >/dev/null 2>&1 || true
    fi
    sudo ip neigh flush dev "$IFACE" 2>/dev/null || true
    exit "$rc"
}

# ---- 1. network ----
say "Configuring $IFACE for the robot subnet ($HOST_IP)"
sudo ip link set "$IFACE" up
trap cleanup EXIT

# Exclusive mode (opt-in): drop other global-scope IPv4 addresses on this NIC
# (e.g. a DHCP 10.x) in case a routable address hijacks DDS multicast routing.
# These are restored on exit by reapplying the NetworkManager connection.
if [ "$EXCLUSIVE" -eq 1 ]; then
    while read -r other; do
        [ -z "$other" ] && continue
        case "$other" in
            "${HOST_IP%/*}"/*|"$HOST_IP") continue ;;          # the one we want
        esac
        case "$other" in
            "$SUBNET_PREFIX"*) continue ;;                      # any other .123.x is fine
        esac
        say "Removing conflicting address $other from $IFACE (restored on exit)"
        sudo ip addr del "$other" dev "$IFACE" && REMOVED_ANY=1
    done < <(ip -o -4 addr show dev "$IFACE" scope global | awk '{print $4}')
fi

# Add the robot host address (as a secondary address) if not already present.
if ip -o -4 addr show dev "$IFACE" | awk '{print $4}' | grep -qx "$HOST_IP"; then
    say "$HOST_IP already on $IFACE"
else
    sudo ip addr add "$HOST_IP" dev "$IFACE" && ADDED_HOST_IP=1
fi
ip -brief addr show "$IFACE"

# ---- 2. reachability ----
say "Flushing neighbor cache on $IFACE"
sudo ip neigh flush dev "$IFACE" || true

say "Pinging robot at $ROBOT_IP"
if ping -c 3 -W 1 "$ROBOT_IP" >/dev/null 2>&1; then
    say "Robot is reachable."
else
    if [ "$FORCE" -eq 1 ]; then
        say "Ping failed but --force given; continuing."
    else
        die "Robot not reachable at $ROBOT_IP. Check cable/power, or try ROBOT_IP=192.168.123.164. (--force to override)"
    fi
fi

# ---- 3. release onboard controller ----
say "Releasing onboard control program (conda env: $CONDA_ENV)"
# shellcheck disable=SC1091
source "$(conda info --base 2>/dev/null)/etc/profile.d/conda.sh" 2>/dev/null \
    || source "$HOME/miniconda3/etc/profile.d/conda.sh"
conda activate "$CONDA_ENV" || die "could not activate conda env '$CONDA_ENV'"

if python "$DEPLOY_DIR/release_onboard_control.py" "$IFACE"; then
    say "Onboard controller OFFLINE -- lowcmd channel is free."
else
    if [ "$FORCE" -eq 1 ]; then
        say "Release reported NOT safe but --force given; continuing anyway."
    else
        die "Onboard controller could not be released. Refusing to start g1_ctrl. (--force to override)"
    fi
fi

# ---- 4. launch ----
say "Launching g1_ctrl --network $IFACE"
say "Controls:  L2+Up -> FixStand,  then R1+X -> run policy."
cd "$DEPLOY_DIR"
# Run in the foreground (not exec) so the EXIT trap restores the network when
# g1_ctrl quits or you Ctrl-C out of it.
"$G1_CTRL" --network "$IFACE"
