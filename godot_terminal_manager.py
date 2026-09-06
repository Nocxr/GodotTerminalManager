from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Header, Input, Label, RichLog, Static


ARCHIVE_URL = "https://godotengine.org/download/archive/"
DEFAULT_LIMIT = 8
CONFIG_PATH = Path(__file__).with_name("config.json")
TEMP_ROOT = Path(__file__).with_name(".tmp")
LOG_PATH = Path(__file__).with_name("app.log")


@dataclass
class GodotVersion:
    name: str
    date: str
    page_url: str
    windows_url: str = ""
    dotnet_url: str = ""
    mac_url: str = ""
    mac_dotnet_url: str = ""


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        self._href = dict(attrs).get("href")
        self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href:
            text = " ".join("".join(self._text).split())
            self.links.append((text, self._href))
            self._href = None
            self._text = []


def fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "GodotEngineTUI/0.1"})
    with urllib.request.urlopen(request, timeout=15) as response:
        return response.read().decode("utf-8", errors="replace")


def download_file(url: str, target: Path, referer: str = ARCHIVE_URL) -> None:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 GodotEngineTUI/0.1",
            "Accept": "application/zip,application/octet-stream,*/*",
            "Referer": referer,
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        with target.open("wb") as output:
            shutil.copyfileobj(response, output)


def parse_links(html: str, base_url: str) -> list[tuple[str, str]]:
    parser = LinkParser()
    parser.feed(html)
    return [(text, urllib.parse.urljoin(base_url, href)) for text, href in parser.links]


def fetch_versions(limit: int = DEFAULT_LIMIT) -> list[GodotVersion]:
    html = fetch_text(ARCHIVE_URL)
    versions: list[GodotVersion] = []
    seen: set[str] = set()

    for text, href in parse_links(html, ARCHIVE_URL):
        match = re.match(r"^(\d+\.\d+(?:\.\d+)?-(?:stable|dev\d+|beta\d+|rc\d+))\s+(.+)$", text)
        if not match or href in seen:
            continue
        seen.add(href)
        versions.append(GodotVersion(match.group(1), match.group(2), href))
        if len(versions) >= limit:
            break

    for version in versions:
        try:
            enrich_download_links(version)
        except (urllib.error.URLError, TimeoutError, OSError):
            continue

    return versions


def enrich_download_links(version: GodotVersion) -> None:
    html = fetch_text(version.page_url)
    for text, href in parse_links(html, version.page_url):
        normalized = text.lower()
        url = href.lower()
        is_windows_editor = normalized.startswith("windows") and "x86_64" in normalized
        is_mac_editor = normalized.startswith("macos") and "universal" in normalized
        is_dotnet = ".net" in normalized or "mono" in url
        if is_windows_editor and not is_dotnet and not version.windows_url:
            version.windows_url = href
        if is_windows_editor and is_dotnet and not version.dotnet_url:
            version.dotnet_url = href
        if is_mac_editor and not is_dotnet and not version.mac_url:
            version.mac_url = href
        if is_mac_editor and is_dotnet and not version.mac_dotnet_url:
            version.mac_dotnet_url = href


def fallback_versions() -> list[GodotVersion]:
    names = [
        ("4.8-dev4", "26 August 2026"),
        ("4.8-dev3", "7 August 2026"),
        ("4.8-dev2", "21 July 2026"),
        ("4.8-dev1", "6 July 2026"),
        ("4.7.2-stable", "18 August 2026"),
    ]
    return [GodotVersion(name, date, urllib.parse.urljoin(ARCHIVE_URL, f"{name}/")) for name, date in names]


def load_config() -> dict[str, str]:
    if sys.platform == "darwin":
        defaults = {
            "engine_dir": str(Path.home() / "godot"),
            "project_dir": str(Path.home() / "projects" / "godot"),
            "plugin_repos": [],
            "active_editor": "",
        }
    else:
        defaults = {
            "engine_dir": r"H:\godot",
            "project_dir": r"H:\projects\godot",
            "plugin_repos": [],
            "active_editor": "",
        }

    if not CONFIG_PATH.exists():
        return defaults

    saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    config = defaults | {key: saved[key] for key in defaults.keys() & saved.keys()}
    if isinstance(config.get("plugin_repos"), str):
        config["plugin_repos"] = [repo.strip() for repo in config["plugin_repos"].splitlines() if repo.strip()]

    if sys.platform == "darwin":
        if re.match(r"^[A-Za-z]:[\\/]", str(config.get("engine_dir", ""))):
            config["engine_dir"] = defaults["engine_dir"]
        if re.match(r"^[A-Za-z]:[\\/]", str(config.get("project_dir", ""))):
            config["project_dir"] = defaults["project_dir"]
    old_engine_dir = str(Path.home() / "Godot" / "Engines")
    old_project_dir = str(Path.home() / "Godot" / "Projects")
    if config["engine_dir"] == old_engine_dir and sys.platform != "darwin":
        config["engine_dir"] = defaults["engine_dir"]
    if config["project_dir"] == old_project_dir and sys.platform != "darwin":
        config["project_dir"] = defaults["project_dir"]
    return config


def save_config(config: dict[str, str]) -> None:
    CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")


def folder_date(folder: Path) -> str:
    try:
        return datetime.fromtimestamp(folder.stat().st_mtime).strftime("%Y-%m-%d")
    except OSError:
        return ""


def find_editor_executable_names(folder: Path) -> list[str]:
    if sys.platform == "darwin":
        return [path.name for path in sorted(folder.rglob("*.app")) if "godot" in path.name.lower()]
    return [path.name for path in sorted(folder.rglob("*.exe")) if "godot" in path.name.lower()]


def guess_editor_version(folder_name: str, executable_names: list[str]) -> str:
    text = " ".join([folder_name, *executable_names])
    match = re.search(r"\d+\.\d+(?:\.\d+)?(?:[-_.](?:stable|dev\d+|beta\d+|rc\d+))?", text, re.IGNORECASE)
    return match.group(0).replace("_", "-") if match else ""


def list_installed_editors(engine_dir: str) -> list[tuple[str, str, str, str]]:
    root = Path(os.path.expandvars(os.path.expanduser(engine_dir)))
    if not root.exists():
        return [("Directory not found", "", "", "")]

    editors: list[tuple[str, str, str, str]] = []
    for folder in sorted(path for path in root.iterdir() if path.is_dir()):
        executable_names = find_editor_executable_names(folder)
        editors.append((folder.name, guess_editor_version(folder.name, executable_names), folder_date(folder), str(folder)))

    return editors or [("No editor folders found", "", "", "")]


def read_project_version(project_file: Path) -> str:
    try:
        text = project_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""

    features = re.search(r'config/features=PackedStringArray\((.*?)\)', text, re.DOTALL)
    if features:
        version = re.search(r'"(\d+\.\d+(?:\.\d+)?)"', features.group(1))
        if version:
            return version.group(1)

    config_version = re.search(r"config_version=(\d+)", text)
    return f"config {config_version.group(1)}" if config_version else ""


def list_projects(project_dir: str) -> list[tuple[str, str, str, str]]:
    root = Path(os.path.expandvars(os.path.expanduser(project_dir)))
    if not root.exists():
        return [("Directory not found", "", "", "")]

    projects: list[tuple[str, str, str, str]] = []
    for folder in sorted(path for path in root.iterdir() if path.is_dir()):
        project_file = folder / "project.godot"
        version = read_project_version(project_file) if project_file.exists() else ""
        projects.append((folder.name, version, folder_date(folder), str(folder)))

    return projects or [("No project folders found", "", "", "")]


def list_plugins(plugin_repos: list[str]) -> list[tuple[str, str]]:
    plugins = [(repo_name(repo), repo) for repo in plugin_repos if repo.strip()]
    return plugins or [("No plugin repos configured", "")]


def repo_name(repo: str) -> str:
    name = repo.rstrip("/").split("/")[-1]
    return name[:-4] if name.endswith(".git") else name


def clone_plugin_repo(repo: str, project_folder: str) -> Path:
    if not repo:
        raise ValueError("No plugin repo selected.")
    addons = Path(project_folder) / "addons"
    addons.mkdir(exist_ok=True)
    target = addons / repo_name(repo)
    if target.exists():
        raise FileExistsError(f"{target.name} already exists in this project's addons folder.")
    subprocess.run(["git", "clone", repo, str(target)], check=True)
    return target


def find_editor_app(editor_folder: Path) -> Path | None:
    if sys.platform != "darwin":
        return None

    for app in sorted(editor_folder.rglob("*.app")):
        if "godot" in app.name.lower() and (app / "Contents" / "MacOS").is_dir():
            return app
    return None


def repair_macos_app_permissions(editor_folder: Path) -> None:
    """Restore executable bits that zipfile extraction may drop from macOS app bundles."""
    if sys.platform != "darwin":
        return

    for app in editor_folder.rglob("*.app"):
        macos_dir = app / "Contents" / "MacOS"
        if not macos_dir.is_dir():
            continue

        for candidate in macos_dir.iterdir():
            if not candidate.is_file():
                continue
            mode = candidate.stat().st_mode
            candidate.chmod(mode | 0o111)


def find_editor_launcher(editor_folder: Path) -> Path | None:
    if sys.platform == "darwin":
        app = find_editor_app(editor_folder)
        if app is None:
            return None

        macos_dir = app / "Contents" / "MacOS"
        preferred = macos_dir / "Godot"
        if preferred.is_file():
            return preferred

        for candidate in sorted(macos_dir.iterdir()):
            if candidate.is_file() and "godot" in candidate.name.lower():
                return candidate
        return None

    if sys.platform.startswith("win"):
        exes = [path for path in sorted(editor_folder.rglob("*.exe")) if "godot" in path.name.lower()]
        return exes[0] if exes else None

    for candidate in sorted(editor_folder.rglob("Godot*")):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def download_and_extract_editor(version: GodotVersion, engine_dir: str, flavor: str) -> Path:
    url = {
        "windows": version.windows_url,
        "dotnet": version.dotnet_url,
        "mac": version.mac_url,
        "mac_dotnet": version.mac_dotnet_url,
    }[flavor]
    if not url:
        raise ValueError(f"No {flavor} download link found for that archive entry.")

    engine_root = Path(os.path.expandvars(os.path.expanduser(engine_dir)))
    engine_root.mkdir(parents=True, exist_ok=True)
    suffix = {
        "windows": "",
        "dotnet": "-dotnet",
        "mac": "-mac",
        "mac_dotnet": "-dotnet-mac",
    }[flavor]
    target = engine_root / f"{version.name}{suffix}"
    if target.exists():
        raise FileExistsError(f"{target.name} already exists.")

    TEMP_ROOT.mkdir(exist_ok=True)
    zip_name = Path(urllib.parse.urlparse(url).path).name or f"{version.name}{suffix}.zip"
    zip_path = TEMP_ROOT / zip_name
    if zip_path.exists():
        zip_path.unlink()

    target.mkdir()
    try:
        download_file(url, zip_path, version.page_url)
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(target)
        flatten_single_child_folder(target)
        repair_macos_app_permissions(target)
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise
    finally:
        zip_path.unlink(missing_ok=True)

    return target


def flatten_single_child_folder(folder: Path) -> None:
    children = [child for child in folder.iterdir()]
    if len(children) != 1 or not children[0].is_dir():
        return

    nested = children[0]

    if nested.suffix.lower() == ".app":
        return

    temp_name = folder.parent / f".{folder.name}-flattening"
    if temp_name.exists():
        shutil.rmtree(temp_name, ignore_errors=True)
    nested.rename(temp_name)
    shutil.rmtree(folder)
    temp_name.rename(folder)


def trash_child_folder(root_dir: str, folder_name: str, label: str) -> None:
    root = Path(os.path.expandvars(os.path.expanduser(root_dir))).resolve()
    target = (root / folder_name).resolve()
    if target == root or root not in target.parents:
        raise ValueError(f"Refusing to trash outside the {label} directory.")
    if not target.is_dir():
        raise FileNotFoundError(folder_name)
    move_to_trash(target)


def move_to_trash(path: Path) -> None:
    try:
        from send2trash import send2trash
    except ModuleNotFoundError:
        send2trash = None

    if send2trash is not None:
        send2trash(str(path))
        return

    if sys.platform.startswith("win"):
        recycle_with_windows_shell(path)
        return

    if sys.platform == "darwin":
        trash_dir = Path.home() / ".Trash"
        trash_dir.mkdir(parents=True, exist_ok=True)

        target = trash_dir / path.name
        counter = 1

        while target.exists():
            target = trash_dir / f"{path.stem} {counter}{path.suffix}"
            counter += 1

        shutil.move(str(path), str(target))
        return

    trash_dir = Path.home() / ".local" / "share" / "Trash" / "files"
    trash_dir.mkdir(parents=True, exist_ok=True)
    target = trash_dir / path.name
    counter = 1
    while target.exists():
        target = trash_dir / f"{path.name}.{counter}"
        counter += 1
    shutil.move(str(path), target)


def recycle_with_windows_shell(path: Path) -> None:
    import ctypes
    from ctypes import wintypes

    FO_DELETE = 3
    FOF_ALLOWUNDO = 0x0040
    FOF_NOCONFIRMATION = 0x0010
    FOF_NOERRORUI = 0x0400
    FOF_SILENT = 0x0004

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", wintypes.UINT),
            ("pFrom", wintypes.LPCWSTR),
            ("pTo", wintypes.LPCWSTR),
            ("fFlags", wintypes.WORD),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", wintypes.LPVOID),
            ("lpszProgressTitle", wintypes.LPCWSTR),
        ]

    absolute_path = str(path.resolve()) + "\0\0"
    operation = SHFILEOPSTRUCTW()
    operation.wFunc = FO_DELETE
    operation.pFrom = absolute_path
    operation.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_NOERRORUI | FOF_SILENT

    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation))
    if result != 0:
        raise OSError(result, f"Windows recycle bin operation failed for {path}")
    if operation.fAnyOperationsAborted:
        raise OSError(f"Windows recycle bin operation was aborted for {path}")


def launch_editor(editor_folder: str) -> None:
    folder = Path(os.path.expandvars(os.path.expanduser(editor_folder)))

    if sys.platform == "darwin":
        app = find_editor_app(folder)
        if app is None:
            raise FileNotFoundError("No Godot .app bundle found in editor folder.")

        # Repair old downloads too, not just newly extracted ones.
        repair_macos_app_permissions(folder)

        launcher = find_editor_launcher(folder)
        if launcher is None:
            raise FileNotFoundError("Godot.app exists, but its Contents/MacOS executable was not found.")
        if not os.access(launcher, os.X_OK):
            raise PermissionError(f"Godot executable is not executable: {launcher}")

        result = subprocess.run(
            ["open", "-n", str(app)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "macOS failed to launch the application.").strip()
            raise RuntimeError(message)
        return

    launcher = find_editor_launcher(folder)
    if launcher is None:
        raise FileNotFoundError("No Godot launcher found in editor folder.")

    subprocess.Popen(
        [str(launcher)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
    )


def write_godot_shim(engine_dir: str, launcher: Path) -> Path:
    if sys.platform == "darwin":
        # launcher is inside Godot.app/Contents/MacOS. Repair the app bundle before
        # writing a shell shim that executes it directly.
        for parent in launcher.parents:
            if parent.suffix.lower() == ".app":
                repair_macos_app_permissions(parent.parent)
                break

    engine_root = Path(os.path.expandvars(os.path.expanduser(engine_dir)))
    engine_root.mkdir(parents=True, exist_ok=True)
    if sys.platform == "darwin":
        shim = engine_root / "godot"
        shim.write_text(f'#!/bin/sh\nexec "{launcher}" "$@"\n', encoding="utf-8")
        shim.chmod(0o755)
        return shim

    shim = engine_root / "godot.cmd"
    shim.write_text(f'@echo off\n"{launcher}" %*\n', encoding="utf-8")
    return shim


def write_manager_shim(engine_dir: str) -> Path:
    engine_root = Path(os.path.expandvars(os.path.expanduser(engine_dir)))
    engine_root.mkdir(parents=True, exist_ok=True)
    python = Path(sys.executable).resolve()
    script = Path(__file__).resolve()

    if sys.platform == "darwin":
        shim = engine_root / "godot"
        shim.write_text(f'#!/bin/sh\nexec "{python}" "{script}" "$@"\n', encoding="utf-8")
        shim.chmod(0o755)
        return shim

    shim = engine_root / "godot.cmd"
    shim.write_text(f'@echo off\n"{python}" "{script}" %*\n', encoding="utf-8")
    return shim


def launch_project(project_folder: str, engine_dir: str, active_editor: str = "", editor_mode: bool = False) -> None:
    if active_editor:
        launcher = find_editor_launcher(Path(active_editor))
        if launcher is None:
            raise FileNotFoundError("Active Godot editor launcher was not found.")
        args = ["--path", project_folder]
        if editor_mode:
            args.insert(0, "--editor")
        subprocess.Popen(
            [str(launcher), *args],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
        return

    editor_root = Path(os.path.expandvars(os.path.expanduser(engine_dir)))
    launchers: list[Path] = []
    if editor_root.exists():
        for folder in sorted(path for path in editor_root.iterdir() if path.is_dir()):
            launcher = find_editor_launcher(folder)
            if launcher:
                launchers.append(launcher)
    if not launchers:
        raise FileNotFoundError("No installed Godot editor found.")

    launcher = launchers[0]
    args = ["--path", project_folder]
    if editor_mode:
        args.insert(0, "--editor")
    subprocess.Popen(
        [str(launcher), *args],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
    )


def open_folder(path: str) -> None:
    resolved = str(Path(os.path.expandvars(os.path.expanduser(path))).resolve())

    if sys.platform.startswith("win"):
        os.startfile(resolved)  # type: ignore[attr-defined]
        return

    command = ["open", "-a", "Finder", resolved] if sys.platform == "darwin" else ["xdg-open", resolved]
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout or f"Failed to open folder: {resolved}").strip()
        raise RuntimeError(message)


def open_file(path: Path) -> None:
    resolved = str(path.resolve())

    if sys.platform.startswith("win"):
        os.startfile(resolved)  # type: ignore[attr-defined]
        return

    command = ["open", resolved] if sys.platform == "darwin" else ["xdg-open", resolved]
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout or f"Failed to open file: {resolved}").strip()
        raise RuntimeError(message)


def copy_to_clipboard(text: str) -> None:
    try:
        import tkinter

        root = tkinter.Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
        root.destroy()
        return
    except Exception:
        pass

    if sys.platform.startswith("win"):
        subprocess.run("clip", input=text, text=True, check=True, shell=True)
    elif sys.platform == "darwin":
        subprocess.run(["pbcopy"], input=text, text=True, check=True)
    else:
        subprocess.run(["xclip", "-selection", "clipboard"], input=text, text=True, check=True)


def trash_label() -> str:
    return "trash" if sys.platform == "darwin" else "recycle bin"


class SettingsPanel(Vertical):
    def __init__(self, config: dict[str, str]) -> None:
        super().__init__(id="settings")
        self.config = config

    def compose(self) -> ComposeResult:
        yield Label("Engine dir")
        yield Input(value=self.config["engine_dir"], id="engine_dir")
        yield Label("Project dir")
        yield Input(value=self.config["project_dir"], id="project_dir")

    def current_config(self) -> dict[str, str]:
        return {
            "engine_dir": self.query_one("#engine_dir", Input).value,
            "project_dir": self.query_one("#project_dir", Input).value,
        }


class SettingsModal(ModalScreen[dict[str, str] | None]):
    CSS = """
    SettingsModal {
        align: center middle;
    }

    #settings-dialog {
        width: 76;
        height: 22;
        padding: 1 2;
        background: #111827;
        border: thick #8bd3ff;
    }

    #settings-title {
        height: 1;
        color: #ffffff;
        text-style: bold;
        content-align: center middle;
    }

    #settings-keys {
        height: 1;
        color: #8bd3ff;
        content-align: center middle;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("s", "save", "Save", show=False),
        Binding("p", "point_godot", "Point Godot", show=False),
    ]

    def __init__(self, config: dict[str, str]) -> None:
        super().__init__()
        self.config = config

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("Settings", id="settings-title"),
            SettingsPanel(self.config),
            Static("s save    p point godot here    esc close", id="settings-keys"),
            id="settings-dialog",
        )

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_save(self) -> None:
        self.dismiss(self.query_one(SettingsPanel).current_config())

    def action_point_godot(self) -> None:
        self.dismiss(self.query_one(SettingsPanel).current_config() | {"point_godot": "1"})


class AddPluginModal(ModalScreen[str | None]):
    CSS = """
    AddPluginModal {
        align: center middle;
    }

    #plugin-dialog {
        width: 78;
        height: 10;
        padding: 1 2;
        background: #111827;
        border: thick #8bd3ff;
    }

    #plugin-title {
        height: 1;
        color: #ffffff;
        text-style: bold;
        content-align: center middle;
    }

    #plugin-keys {
        height: 1;
        color: #8bd3ff;
        content-align: center middle;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("enter", "save", "Save", show=False),
    ]

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("Add Plugin Repo", id="plugin-title"),
            Input(value="http://github.com/", id="plugin_url"),
            Static("enter add    esc close", id="plugin-keys"),
            id="plugin-dialog",
        )

    def on_mount(self) -> None:
        plugin_url = self.query_one("#plugin_url", Input)
        plugin_url.focus()
        plugin_url.cursor_position = len(plugin_url.value)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_save(self) -> None:
        value = self.query_one("#plugin_url", Input).value.strip()
        self.dismiss(value or None)

    @on(Input.Submitted, "#plugin_url")
    def plugin_url_submitted(self) -> None:
        self.action_save()


class ProjectPickerModal(ModalScreen[tuple[str, str, str, str] | None]):
    CSS = """
    ProjectPickerModal {
        align: center middle;
    }

    #project-picker-dialog {
        width: 78;
        height: 20;
        padding: 1 2;
        background: #111827;
        border: thick #8bd3ff;
    }

    #project-picker-title {
        height: 1;
        color: #ffffff;
        text-style: bold;
        content-align: center middle;
    }

    #project-picker-keys {
        height: 1;
        color: #8bd3ff;
        content-align: center middle;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("enter", "choose", "Choose", show=False),
    ]

    def __init__(self, projects: list[tuple[str, str, str, str]]) -> None:
        super().__init__()
        self.projects = [
            project
            for project in projects
            if project[0] not in {"Directory not found", "No project folders found"}
        ]

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("Clone Into Project", id="project-picker-title"),
            DataTable(id="project_picker"),
            Static("enter choose    esc close", id="project-picker-keys"),
            id="project-picker-dialog",
        )

    def on_mount(self) -> None:
        table = self.query_one("#project_picker", DataTable)
        table.add_columns("Project", "Version", "Date")
        for name, version, date, _path in self.projects:
            table.add_row(name, version, date)
        if self.projects:
            table.move_cursor(row=0, column=0)
        table.focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_choose(self) -> None:
        table = self.query_one("#project_picker", DataTable)
        if table.cursor_row is None or table.cursor_row >= len(self.projects):
            self.dismiss(None)
            return
        self.dismiss(self.projects[table.cursor_row])

    @on(DataTable.RowSelected, "#project_picker")
    def project_row_selected(self) -> None:
        self.action_choose()

    def on_key(self, event: object) -> None:
        if getattr(event, "key", None) == "enter":
            self.action_choose()
            stop = getattr(event, "stop", None)
            if callable(stop):
                stop()


class ConfirmTrashModal(ModalScreen[bool]):
    CSS = """
    ConfirmTrashModal {
        align: center middle;
    }

    #confirm-dialog {
        width: 54;
        height: 11;
        padding: 1 3;
        background: #111827;
        border: thick #8bd3ff;
    }

    #confirm-title {
        height: 1;
        color: #ffffff;
        text-style: bold;
        content-align: center middle;
    }

    #confirm-message {
        height: 2;
        color: #d7deea;
        margin-top: 1;
        content-align: center middle;
    }

    #confirm-keys {
        height: 3;
        color: #8bd3ff;
        margin-bottom: 1;
        content-align: center middle;
        background: #0d1117;
        border: solid #263245;
    }

    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("n", "cancel", "Cancel", show=False),
        Binding("y", "confirm", "Confirm", show=False),
        Binding("enter", "confirm", "Confirm", show=False),
    ]

    def __init__(self, kind: str, name: str) -> None:
        super().__init__()
        self.kind = kind
        self.item_name = name

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static(f"Move {self.kind} to {trash_label()}?", id="confirm-title"),
            Static(self.item_name, id="confirm-message"),
            Static("[ y / enter ] confirm      [ n / esc ] cancel", id="confirm-keys"),
            id="confirm-dialog",
        )

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_confirm(self) -> None:
        self.dismiss(True)

class GodotManagerApp(App):
    CSS = """
    Screen {
        background: #0d1117;
        color: #d7deea;
    }

    Header {
        background: #111827;
        color: #d7deea;
    }

    #layout {
        height: 1fr;
    }

    #left {
        width: 42%;
        min-width: 48;
        border: solid #263245;
    }

    #projects-box {
        height: 2fr;
    }

    #editors-box, #archive-box, #plugins-box, #log-box {
        height: 1fr;
    }

    #right {
        width: 58%;
        border: solid #263245;
    }

    #settings {
        height: 17;
        padding: 0 2;
        border-bottom: solid #263245;
        background: #111827;
    }

    Label {
        height: 1;
        color: #9fb4d3;
        margin-top: 0;
    }

    Input {
        height: 3;
        background: #0d1117;
        border: tall #31415b;
        color: #e5edf8;
    }

    .section-title {
        height: 1;
        padding: 0 1;
        background: #172033;
        color: #8bd3ff;
        text-style: bold;
    }

    DataTable {
        height: 1fr;
        background: #0d1117;
        color: #d7deea;
        border: none;
    }

    #status {
        height: 1;
        padding: 0 1;
        background: #0f1724;
        color: #8bd3ff;
        text-style: bold;
    }

    #log-title {
        height: 1;
        padding: 0 1;
        background: #172033;
        color: #8bd3ff;
        text-style: bold;
    }

    #log {
        height: 1fr;
        padding: 0 1;
        background: #0b0f16;
        color: #9fb4d3;
        border-top: solid #263245;
    }
    """

    BINDINGS = [
        Binding("tab", "focus_next", "Next", show=False),
        Binding("shift+tab", "focus_previous", "Previous", show=False),
        Binding("enter", "open_selected", "Open", show=False),
        Binding("r", "refresh", "Refresh", show=False),
        Binding("o", "open_selected", "Open", show=False),
        Binding("c", "copy_or_clone_plugin", "Copy/Clone", show=False),
        Binding("l", "launch_project", "Launch", show=False),
        Binding("s", "standard_or_save", "Standard/Save", show=False),
        Binding("n", "download_dotnet", ".NET", show=False),
        Binding("a", "active_or_add_plugin", "Active/Add", show=False),
        Binding("f", "open_folder", "Folder", show=False),
        Binding("g", "open_settings", "Settings", show=False),
        Binding("delete", "delete_selected", "Delete", show=False),
        Binding("backspace", "delete_selected", "Delete", show=False),
        Binding("q", "quit", "Quit", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.config = load_config()
        self.versions: list[GodotVersion] = []
        self.editors: list[tuple[str, str, str, str]] = []
        self.projects: list[tuple[str, str, str, str]] = []
        self.plugins: list[tuple[str, str]] = []
        self.log_lines: list[str] = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="layout"):
            with Vertical(id="left"):
                with Vertical(id="projects-box"):
                    yield Static("Projects", classes="section-title")
                    yield DataTable(id="projects")
                with Vertical(id="editors-box"):
                    yield Static("Installed Editors", classes="section-title")
                    yield DataTable(id="editors")
            with Vertical(id="right"):
                with Vertical(id="archive-box"):
                    yield Static("Godot archive", classes="section-title")
                    yield DataTable(id="versions")
                with Vertical(id="plugins-box"):
                    yield Static("Plugins", classes="section-title")
                    yield DataTable(id="plugins")
                with Vertical(id="log-box"):
                    yield Static("Log", id="log-title")
                    yield RichLog(id="log", highlight=False, markup=False, wrap=True)
        yield Static("Ready", id="status")

    def on_mount(self) -> None:
        self.title = "Godot Terminal Manager"
        self._setup_tables()
        self.query_one("#log", RichLog).can_focus = True
        self.query_one("#projects", DataTable).focus()
        self.set_status("Pulling archive list...")
        self.run_worker(self.refresh_archive, thread=True)
        self.run_worker(self.refresh_editors, thread=True)
        self.run_worker(self.refresh_projects, thread=True)
        self.refresh_plugins()

    def _setup_tables(self) -> None:
        versions = self.query_one("#versions", DataTable)
        versions.add_columns("Version", "Date")
        self.query_one("#editors", DataTable).add_columns("Active", "Editor", "Version", "Date")
        self.query_one("#projects", DataTable).add_columns("Projects", "Version", "Date")
        self.query_one("#plugins", DataTable).add_columns("Plugin", "Repo")

    def refresh_archive(self) -> None:
        self.call_from_thread(self.set_status, "Pulling archive list...")
        self.call_from_thread(self.add_log, "Fetching Godot archive...")
        try:
            versions = fetch_versions()
        except (urllib.error.URLError, TimeoutError, OSError):
            versions = fallback_versions()
            self.call_from_thread(self.add_log, "Archive fetch failed; showing fallback versions.")
        else:
            self.call_from_thread(self.add_log, "Archive loaded.")
        self.call_from_thread(self.populate_archive, versions)

    def refresh_editors(self) -> None:
        self.call_from_thread(self.add_log, "Refreshing installed editors...")
        self.call_from_thread(self.populate_editors, list_installed_editors(self.config["engine_dir"]))
        self.call_from_thread(self.add_log, "Installed editors refreshed.")

    def refresh_projects(self) -> None:
        self.call_from_thread(self.add_log, "Refreshing projects...")
        self.call_from_thread(self.populate_projects, list_projects(self.config["project_dir"]))
        self.call_from_thread(self.add_log, "Projects refreshed.")

    def refresh_plugins(self) -> None:
        self.add_log("Refreshing plugins...")
        self.populate_plugins(list_plugins(self.config.get("plugin_repos", [])))
        self.add_log("Plugins refreshed.")

    def populate_archive(self, versions: list[GodotVersion]) -> None:
        self.versions = versions
        table = self.query_one("#versions", DataTable)
        table.clear()
        for version in versions:
            table.add_row(version.name, version.date)
        self.set_context_status()

    def populate_editors(self, editors: list[tuple[str, str, str, str]]) -> None:
        self.editors = editors
        table = self.query_one("#editors", DataTable)
        table.clear()
        for name, version, date, _path in editors:
            active = "*" if _path == self.config.get("active_editor", "") else ""
            table.add_row(active, name, version, date)

    def populate_projects(self, projects: list[tuple[str, str, str, str]]) -> None:
        self.projects = projects
        table = self.query_one("#projects", DataTable)
        table.clear()
        for name, version, date, _path in projects:
            table.add_row(name, version, date)

    def populate_plugins(self, plugins: list[tuple[str, str]]) -> None:
        self.plugins = plugins
        table = self.query_one("#plugins", DataTable)
        table.clear()
        for name, repo in plugins:
            table.add_row(name, repo)

    def action_refresh(self) -> None:
        section = self.active_section()
        if section == "archive":
            self.run_worker(self.refresh_archive, thread=True)
        elif section == "editors":
            self.run_worker(self.refresh_editors, thread=True)
        elif section == "projects":
            self.run_worker(self.refresh_projects, thread=True)
        elif section == "plugins":
            self.refresh_plugins()
        else:
            self.run_worker(self.refresh_archive, thread=True)
            self.run_worker(self.refresh_editors, thread=True)
            self.run_worker(self.refresh_projects, thread=True)
            self.refresh_plugins()

    def save_settings(self, settings: dict[str, str]) -> None:
        self.config = settings | {
            "active_editor": self.config.get("active_editor", ""),
            "plugin_repos": self.config.get("plugin_repos", []),
        }
        save_config(self.config)
        self.add_log("Settings saved.")
        self.run_worker(self.refresh_editors, thread=True)
        self.run_worker(self.refresh_projects, thread=True)
        self.refresh_plugins()

    def action_focus_next(self) -> None:
        self.screen.focus_next()
        self.set_timer(0.05, self.set_context_status)

    def action_focus_previous(self) -> None:
        self.screen.focus_previous()
        self.set_timer(0.05, self.set_context_status)

    @on(DataTable.CellSelected, "#editors")
    def editor_cell_selected(self) -> None:
        self.action_open_selected()

    @on(DataTable.RowSelected, "#editors")
    def editor_row_selected(self) -> None:
        self.action_open_selected()

    @on(DataTable.CellSelected, "#projects")
    def project_cell_selected(self) -> None:
        self.action_open_selected()

    @on(DataTable.RowSelected, "#projects")
    def project_row_selected_main(self) -> None:
        self.action_open_selected()

    def action_open_selected(self) -> None:
        section = self.active_section()
        if section == "log":
            try:
                open_file(LOG_PATH)
            except Exception as error:
                self.add_log(f"Open log file failed: {error}")
                return
            self.add_log(f"Opened {LOG_PATH.name}.")
            return
        if section == "editors":
            editor = self.selected_editor()
            if editor is None:
                self.add_log("Select an installed editor first.")
                return
            try:
                launch_editor(editor[3])
            except Exception as error:
                self.add_log(f"Open editor failed: {error}")
                return
            self.add_log(f"Launched {editor[0]}.")
        elif section == "projects":
            project = self.selected_project()
            if project is None:
                self.add_log("Select a project first.")
                return
            try:
                launch_project(project[3], self.config["engine_dir"], self.config.get("active_editor", ""), editor_mode=True)
            except Exception as error:
                self.add_log(f"Open project in editor failed: {error}")
                return
            self.add_log(f"Opened {project[0]} in editor.")
        else:
            self.set_context_status()

    def action_launch_project(self) -> None:
        if self.active_section() != "projects":
            self.set_context_status()
            return
        project = self.selected_project()
        if project is None:
            self.add_log("Select a project first.")
            return
        try:
            launch_project(project[3], self.config["engine_dir"], self.config.get("active_editor", ""), editor_mode=False)
        except Exception as error:
            self.add_log(f"Launch project failed: {error}")
            return
        self.add_log(f"Launched {project[0]}.")

    def action_copy_or_clone_plugin(self) -> None:
        section = self.active_section()
        if section == "plugins":
            self.start_plugin_clone()
            return
        if section != "log":
            self.set_context_status()
            return
        if not self.log_lines:
            self.set_status("No log lines to copy.")
            return
        try:
            copy_to_clipboard(self.log_lines[-1])
        except Exception as error:
            self.set_status(f"Copy failed: {error}")
            return
        self.set_status("Copied last log line.")

    def start_plugin_clone(self) -> None:
        if self.active_section() != "plugins":
            self.set_context_status()
            return
        plugin = self.selected_plugin()
        if plugin is None or not plugin[1]:
            self.add_log("Select a plugin repo first.")
            return
        valid_projects = [
            project
            for project in self.projects
            if project[0] not in {"Directory not found", "No project folders found"}
        ]
        if not valid_projects:
            self.add_log("No projects available to clone into.")
            return
        self.push_screen(ProjectPickerModal(valid_projects), lambda project: self.finish_plugin_clone(plugin, project))

    def finish_plugin_clone(self, plugin: tuple[str, str], project: tuple[str, str, str, str] | None) -> None:
        if project is None:
            self.add_log("Plugin clone canceled.")
            self.set_context_status()
            return
        self.add_log(f"Cloning {plugin[0]} into {project[0]}...")
        self.run_worker(lambda: self.install_plugin_worker(plugin, project), thread=True)

    def install_plugin_worker(self, plugin: tuple[str, str], project: tuple[str, str, str, str]) -> None:
        try:
            target = clone_plugin_repo(plugin[1], project[3])
        except Exception as error:
            self.call_from_thread(self.add_log, f"Plugin clone failed: {type(error).__name__}: {error}")
            return
        self.call_from_thread(self.add_log, f"Installed plugin {plugin[0]} at {target}.")

    def action_open_folder(self) -> None:
        if self.active_section() != "projects":
            if self.active_section() == "editors":
                editor = self.selected_editor()
                if editor is None:
                    self.add_log("Select an installed editor first.")
                    return
                try:
                    open_folder(editor[3])
                except Exception as error:
                    self.add_log(f"Open editor folder failed: {error}")
                    return
                self.add_log(f"Opened folder for {editor[0]}.")
            else:
                self.set_context_status()
            return
        project = self.selected_project()
        if project is None:
            self.add_log("Select a project first.")
            return
        try:
            open_folder(project[3])
        except Exception as error:
            self.add_log(f"Open project folder failed: {error}")
            return
        self.add_log(f"Opened folder for {project[0]}.")

    def action_active_or_add_plugin(self) -> None:
        section = self.active_section()
        if section == "plugins":
            self.open_add_plugin()
            return
        if section != "editors":
            self.set_context_status()
            return
        editor = self.selected_editor()
        if editor is None or editor[0] in {"Directory not found", "No editor folders found"}:
            self.add_log("Select an installed editor first.")
            return
        launcher = find_editor_launcher(Path(editor[3]))
        if launcher is None:
            self.add_log("Set active failed: no Godot launcher found in editor folder.")
            return
        self.config = self.config | {"active_editor": editor[3]}
        save_config(self.config)
        try:
            shim = write_godot_shim(self.config["engine_dir"], launcher)
        except Exception as error:
            self.add_log(f"Active editor saved, but shim failed: {error}")
        else:
            self.add_log(f"Active editor set to {editor[0]}; wrote {shim.name}.")
        self.populate_editors(self.editors)

    def open_add_plugin(self) -> None:
        self.push_screen(AddPluginModal(), self.finish_add_plugin)

    def finish_add_plugin(self, repo: str | None) -> None:
        if not repo:
            self.set_context_status()
            return
        repos = list(self.config.get("plugin_repos", []))
        if repo in repos:
            self.add_log("Plugin repo is already in the list.")
            return
        repos.append(repo)
        self.config = self.config | {"plugin_repos": repos}
        save_config(self.config)
        self.add_log(f"Added plugin repo {repo_name(repo)}.")
        self.refresh_plugins()

    def action_standard_or_save(self) -> None:
        section = self.active_section()
        if section == "settings":
            self.open_settings()
            return
        if section != "archive":
            self.set_context_status()
            return
        flavor = "mac" if sys.platform == "darwin" else "windows"
        self.download_selected(flavor)

    def action_open_settings(self) -> None:
        self.open_settings()

    def open_settings(self) -> None:
        self.push_screen(SettingsModal(self.config), self.finish_settings)

    def finish_settings(self, settings: dict[str, str] | None) -> None:
        if settings is None:
            self.set_context_status()
            return
        point_godot = settings.pop("point_godot", "") == "1"
        self.save_settings(settings)
        if point_godot:
            try:
                shim = write_manager_shim(self.config["engine_dir"])
            except Exception as error:
                self.add_log(f"Could not point godot to this manager: {error}")
            else:
                self.add_log(f"Pointed godot at this manager with {shim.name}.")

    def action_download_dotnet(self) -> None:
        if self.active_section() != "archive":
            self.set_context_status()
            return
        flavor = "mac_dotnet" if sys.platform == "darwin" else "dotnet"
        self.download_selected(flavor)

    def download_selected(self, flavor: str) -> None:
        version = self.selected_version()
        if version is None:
            self.add_log("Select an archive version first.")
            return
        label = {
            "windows": "Windows",
            "dotnet": "Windows .NET",
            "mac": "macOS",
            "mac_dotnet": "macOS .NET",
        }[flavor]
        self.add_log(f"Downloading {version.name} {label}...")
        self.run_worker(lambda: self.download_worker(version, flavor), thread=True)

    def download_worker(self, version: GodotVersion, flavor: str) -> None:
        try:
            target = download_and_extract_editor(version, self.config["engine_dir"], flavor)
        except Exception as error:
            self.call_from_thread(self.add_log, f"Download failed: {type(error).__name__}: {error}")
            return
        self.call_from_thread(self.add_log, f"Installed {target.name}.")
        self.call_from_thread(lambda: self.run_worker(self.refresh_editors, thread=True))

    def action_delete_selected(self) -> None:
        section = self.active_section()
        if section == "editors":
            self.delete_selected_editor()
        elif section == "projects":
            self.delete_selected_project()
        elif section == "plugins":
            self.delete_selected_plugin()
        else:
            self.set_context_status()

    def delete_selected_plugin(self) -> None:
        plugin = self.selected_plugin()
        if plugin is None or not plugin[1]:
            self.add_log("Select a plugin repo first.")
            return
        repos = [repo for repo in self.config.get("plugin_repos", []) if repo != plugin[1]]
        self.config = self.config | {"plugin_repos": repos}
        save_config(self.config)
        self.add_log(f"Removed plugin repo {plugin[0]}.")
        self.refresh_plugins()

    def delete_selected_editor(self) -> None:
        editor = self.selected_editor()
        if editor is None:
            self.add_log("Select an installed editor first.")
            return
        folder_name = editor[0]
        if folder_name in {"Directory not found", "No editor folders found"}:
            self.add_log("Select an editor folder first.")
            return
        self.push_screen(ConfirmTrashModal("editor", folder_name), lambda confirmed: self.finish_delete_editor(editor, confirmed))

    def finish_delete_editor(self, editor: tuple[str, str, str, str], confirmed: bool) -> None:
        if not confirmed:
            self.add_log("Editor move canceled.")
            self.set_context_status()
            return
        folder_name = editor[0]
        try:
            trash_child_folder(self.config["engine_dir"], folder_name, "engine")
        except Exception as error:
            self.add_log(f"Delete failed: {error}")
            return
        self.add_log(f"Moved editor {folder_name} to the {trash_label()}.")
        self.run_worker(self.refresh_editors, thread=True)

    def delete_selected_project(self) -> None:
        project = self.selected_project()
        if project is None:
            self.add_log("Select a project first.")
            return
        folder_name = project[0]
        if folder_name in {"Directory not found", "No project folders found"}:
            self.add_log("Select a project folder first.")
            return
        self.push_screen(ConfirmTrashModal("project", folder_name), lambda confirmed: self.finish_delete_project(project, confirmed))

    def finish_delete_project(self, project: tuple[str, str, str, str], confirmed: bool) -> None:
        if not confirmed:
            self.add_log("Project move canceled.")
            self.set_context_status()
            return
        folder_name = project[0]
        try:
            trash_child_folder(self.config["project_dir"], folder_name, "project")
        except Exception as error:
            self.add_log(f"Delete failed: {error}")
            return
        self.add_log(f"Moved project {folder_name} to the {trash_label()}.")
        self.run_worker(self.refresh_projects, thread=True)

    def selected_version(self) -> GodotVersion | None:
        table = self.query_one("#versions", DataTable)
        if table.cursor_row is None or table.cursor_row >= len(self.versions):
            return None
        return self.versions[table.cursor_row]

    def selected_editor(self) -> tuple[str, str, str, str] | None:
        table = self.query_one("#editors", DataTable)
        if table.cursor_row is None or table.cursor_row >= len(self.editors):
            return None
        return self.editors[table.cursor_row]

    def selected_project(self) -> tuple[str, str, str, str] | None:
        table = self.query_one("#projects", DataTable)
        if table.cursor_row is None or table.cursor_row >= len(self.projects):
            return None
        return self.projects[table.cursor_row]

    def selected_plugin(self) -> tuple[str, str] | None:
        table = self.query_one("#plugins", DataTable)
        if table.cursor_row is None or table.cursor_row >= len(self.plugins):
            return None
        return self.plugins[table.cursor_row]

    def active_section(self) -> str:
        focused = self.focused
        if isinstance(focused, DataTable):
            if focused.id == "versions":
                return "archive"
            if focused.id == "editors":
                return "editors"
            if focused.id == "projects":
                return "projects"
            if focused.id == "plugins":
                return "plugins"
        if isinstance(focused, RichLog) and focused.id == "log":
            return "log"
        return "settings"

    def set_status(self, message: str) -> None:
        self.query_one("#status", Static).update(message)

    def add_log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"{timestamp}  {message}"
        self.log_lines.append(line)
        self.log_lines = self.log_lines[-200:]
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as log_file:
            log_file.write(line + "\n")
        self.query_one("#log", RichLog).write(line)

    def set_context_status(self) -> None:
        section = self.active_section()
        if section == "archive":
            keys = "Archive keys: r refresh | s download standard | n download .NET | g settings"
        elif section == "editors":
            keys = "Installed editor keys: r refresh | o open editor | a set active | f open folder | delete/backspace confirm trash | g settings"
        elif section == "projects":
            keys = "Project keys: r refresh | o open in editor | l launch project | f open folder | delete/backspace confirm trash | g settings"
        elif section == "plugins":
            keys = "Plugin keys: r refresh | a add repo | c clone into project | delete/backspace remove repo | g settings"
        elif section == "log":
            keys = "Log keys: c copy last | o open log file | g settings"
        else:
            keys = "Global keys: g settings | q quit"
        self.set_status(keys)

    def on_data_table_focus(self, _event: object) -> None:
        self.set_context_status()

    def on_focus(self, _event: object) -> None:
        self.set_context_status()

    def on_click(self, event: object) -> None:
        widget = getattr(event, "widget", None)
        if isinstance(widget, DataTable):
            widget.focus()
            self.set_context_status()
        elif isinstance(widget, RichLog):
            widget.focus()
            self.set_context_status()


if __name__ == "__main__":
    GodotManagerApp().run()
