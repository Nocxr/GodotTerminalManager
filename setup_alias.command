```zsh
#!/bin/zsh

clear

echo
echo "========================================"
echo "  Godot Terminal Manager Alias Setup"
echo "========================================"
echo

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MANAGER="$SCRIPT_DIR/godot_terminal_manager.py"
ZSHRC="$HOME/.zshrc"

echo "Setup script:"
echo "  $0"
echo
echo "Manager:"
echo "  $MANAGER"
echo
echo "zsh profile:"
echo "  $ZSHRC"
echo

if [[ ! -f "$MANAGER" ]]; then
    echo "ERROR:"
    echo "godot_terminal_manager.py was not found next to this setup script."
    echo
    read -k 1 "?Press any key to close..."
    echo
    exit 1
fi

touch "$ZSHRC"

python3 - "$ZSHRC" "$MANAGER" <<'PY'
import re
import sys
from pathlib import Path

zshrc = Path(sys.argv[1]).expanduser()
manager = sys.argv[2]

content = zshrc.read_text(encoding="utf-8") if zshrc.exists() else ""

desired = f'''godot() {{
    python3 "{manager}" "$@"
}}'''

pattern = r'(?ms)^godot\(\)\s*\{.*?^\}'

match = re.search(pattern, content)

if match:
    print("Existing godot function found:")
    print()
    print(match.group(0))
    print()

    if match.group(0) == desired:
        print("OK: godot already points to the correct location.")
    else:
        print("Path/function does not match. Updating...")
        content = re.sub(pattern, lambda _: desired, content, count=1)
        zshrc.write_text(content, encoding="utf-8")

        print()
        print("Updated godot function:")
        print()
        print(desired)
else:
    print("No godot function found. Adding it...")

    if content and not content.endswith("\n"):
        content += "\n"

    content += "\n" + desired + "\n"

    zshrc.write_text(content, encoding="utf-8")

    print()
    print("Added godot function:")
    print()
    print(desired)

print()
print(f"godot -> {manager}")
PY

RESULT=$?

echo

if [[ $RESULT -ne 0 ]]; then
    echo "ERROR: Setup failed."
else
    echo "========================================"
    echo "Setup complete."
    echo "========================================"
    echo
    echo "Open a NEW Terminal window and type:"
    echo
    echo "  godot"
    echo
    echo "Or reload the current shell with:"
    echo
    echo "  source ~/.zshrc"
fi

echo
read -k 1 "?Press any key to close..."
echo
```