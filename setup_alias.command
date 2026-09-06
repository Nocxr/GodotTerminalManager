#!/bin/zsh

echo
echo "========================================"
echo " Godot Terminal Manager Alias Setup"
echo "========================================"
echo

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MANAGER="$SCRIPT_DIR/godot_terminal_manager.py"
ZSHRC="$HOME/.zshrc"

echo "Script directory:"
echo "  $SCRIPT_DIR"
echo

echo "Manager path:"
echo "  $MANAGER"
echo

echo "zsh config:"
echo "  $ZSHRC"
echo

if [[ ! -f "$MANAGER" ]]; then
    echo "ERROR: godot_terminal_manager.py was not found."
    echo "It must be in the same folder as this setup script."
    echo
    read "?Press Enter to close..."
    exit 1
fi

touch "$ZSHRC"

START_MARKER="# >>> Godot Terminal Manager >>>"
END_MARKER="# <<< Godot Terminal Manager <<<"

NEW_BLOCK="$START_MARKER
godot() {
    python3 \"$MANAGER\" \"\$@\"
}
$END_MARKER"

echo "Checking existing godot function..."
echo

if grep -qF "$START_MARKER" "$ZSHRC"; then
    echo "Existing managed godot entry found."
    echo "Updating it..."

    python3 - "$ZSHRC" "$START_MARKER" "$END_MARKER" "$NEW_BLOCK" <<'PY'
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
start = sys.argv[2]
end = sys.argv[3]
new_block = sys.argv[4]

content = path.read_text(encoding="utf-8")

pattern = re.escape(start) + r".*?" + re.escape(end)

content = re.sub(
    pattern,
    lambda _: new_block,
    content,
    count=1,
    flags=re.S,
)

path.write_text(content, encoding="utf-8")
PY

else
    echo "No managed godot entry found."
    echo "Adding it..."

    {
        echo
        echo "$NEW_BLOCK"
        echo
    } >> "$ZSHRC"
fi

echo
echo "Result:"
echo
echo "$NEW_BLOCK"
echo

echo "========================================"
echo " Setup complete"
echo "========================================"
echo
echo "Open a new Terminal window and run:"
echo
echo "  godot"
echo
echo "Or activate it right now with:"
echo
echo "  source ~/.zshrc"
echo

read "?Press Enter to close..."