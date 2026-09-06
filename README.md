# Godot Terminal Manager

A first-pass dark Textual app for browsing recent Godot archive versions, downloading platform-appropriate editors, and scanning installed editors/projects.

Default folders on Windows:

- Engines: `H:\godot`
- Projects: `H:\projects\godot`
- Plugins: `H:\godot\plugins`

Default folders on macOS:

- Engines: `~/godot`
- Projects: `~/projects/godot`
- Plugins: `~/godot/plugins`

Press `g` from any section to open settings.

## Run

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python godot_terminal_manager.py
```

If `python` is not on PATH, install Python 3.11+ from python.org or the Microsoft Store, then rerun the commands.

## Controls

The active keys depend on the focused section.

Archive:

- `r`: refresh archive
- `s`: download and extract the selected standard editor
- `n`: download and extract the selected .NET x86_64 editor on Windows
- `g`: open settings

Installed editors:

- `r`: refresh editors
- `o` / `enter`: launch the selected editor
- `a`: set the selected editor as active
- `f`: open the selected editor folder
- `delete`: show a confirmation popup, then move the selected editor folder to the recycle bin/trash

Projects:

- `r`: refresh projects
- `o` / `enter`: open the selected project in the editor
- `l`: launch the selected project
- `f`: open the selected project folder
- `delete`: show a confirmation popup, then move the selected project folder to the recycle bin/trash

Plugins:

- `r`: refresh plugins
- `a`: add a GitHub repo URL
- `c`: choose a project, then clone the selected GitHub repo into its `addons` folder
- `delete`: remove the selected repo from the list
- `g`: open settings

Log:

- `c`: copy the latest log line
- `o`: open `app.log`

Settings:

- `g`: open directory settings
- `s`: save directory settings while the settings popup is open
- `p`: write a `godot` launcher in the engine dir that opens this manager
- `q`: quit

Directory settings and the active editor are stored in `config.json`.
Plugin repos are managed from the Plugins panel and stored in `config.json`.
Setting an active editor also writes `godot.cmd` on Windows or `godot` on macOS inside the engine directory.
In Settings, `p` writes that same command name to launch Godot Terminal Manager itself instead; put the engine directory on PATH to use it from any terminal.
The on-screen log is also written to `app.log` next to the app for easier copying.
