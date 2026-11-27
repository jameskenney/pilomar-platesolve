#!/usr/bin/env bash
# Install pilomar-platesolve next to Pi-lomar. Safe to run more than once.
#
#   git clone https://github.com/<you>/pilomar-platesolve.git ~/pilomar-platesolve
#   cd ~/pilomar-platesolve && ./install.sh
#
# What it does:
#   * installs astrometry.net + the 2MASS index files from apt, if missing
#     (the same two packages Pi-lomar's scripts/astrometry.net installs)
#   * installs tmux (optional, used only for automatic Tune corrections)
#   * creates ~/.local/bin/pilomar-ps
#   * writes ~/pilomar-platesolve/config.json if you don't have one
# What it never does: touch anything inside /home/pi/pilomar.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="$HOME/.local/bin"

need_pkg() { dpkg -s "$1" >/dev/null 2>&1 || MISSING+=("$1"); }
MISSING=()
need_pkg astrometry.net
need_pkg astrometry-data-2mass-08-19
need_pkg tmux

if ((${#MISSING[@]})); then
  echo "Installing: ${MISSING[*]}"
  sudo apt-get update
  sudo apt-get install -y "${MISSING[@]}"
else
  echo "astrometry.net, index files and tmux already installed."
fi

python3 - <<'PY'
import sys
if sys.version_info < (3, 10):
    sys.exit("Python 3.10 or newer is required")
PY

mkdir -p "$BIN"
cat > "$BIN/pilomar-ps" <<EOF
#!/usr/bin/env bash
PYTHONPATH="$HERE\${PYTHONPATH:+:\$PYTHONPATH}" exec python3 -m pilomar_platesolve "\$@"
EOF
chmod +x "$BIN/pilomar-ps"
echo "Installed $BIN/pilomar-ps"

case ":$PATH:" in
  *":$BIN:"*) ;;
  *) echo "Note: add $BIN to your PATH (log out and back in usually does it on Raspberry Pi OS)." ;;
esac

if [ ! -f "$HERE/config.json" ]; then
  cp "$HERE/config.example.json" "$HERE/config.json"
  echo "Created $HERE/config.json - edit it to suit your build."
fi

echo
"$BIN/pilomar-ps" check || true
