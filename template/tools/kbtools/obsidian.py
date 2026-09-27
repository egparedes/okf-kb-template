"""`kb obsidian setup`: install the vault's community plugins from pinned releases.

The vault lists its plugins in `kb/.obsidian/community-plugins.json`. For
each one pinned in `tools/obsidian-plugins.json`, the release files are
downloaded from GitHub, checked against their SHA-256, and written to
`kb/.obsidian/plugins/<id>/`. Plugin code stays out of git (`.gitignore`).

Two steps stay manual, because Obsidian keeps them outside the vault:
trusting the vault's plugins on first open, and Templater's per-device
"Trigger Templater on new file creation".
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

from .bundle import Bundle
from .resources import child_env

PINS = Path("tools") / "obsidian-plugins.json"
RELEASE_URL = "https://github.com/{repo}/releases/download/{version}/{file}"
ASSETS = ("main.js", "styles.css", "manifest.json")  # manifest last: it marks a complete install


def load_pins(bundle: Bundle) -> dict[str, dict]:
    path = bundle.repo_root / PINS
    if not path.is_file():
        raise SystemExit(f"kb: {PINS} is missing (it comes with the template)")
    return json.loads(path.read_text(encoding="utf-8"))["plugins"]


def _download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "okf-kb-template"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - fixed https URL
            return response.read()
    except (urllib.error.URLError, OSError) as exc:
        raise SystemExit(f"kb: cannot download {url}: {exc}") from None


def _version(text: str | None) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", text or ""))


def _installed_version(folder: Path) -> str | None:
    try:
        return json.loads((folder / "manifest.json").read_text(encoding="utf-8")).get("version")
    except (OSError, ValueError):
        return None


def install(folder: Path, pin: dict, force: bool = False, fetch=_download) -> str:
    """Install one plugin; returns what happened. Nothing is written unless every file verifies."""
    installed = _installed_version(folder)
    if installed and not force:
        if installed == pin["version"]:
            return f"{installed} already installed"
        if _version(installed) > _version(pin["version"]):
            return f"{installed} installed, newer than the pinned {pin['version']}: kept (--force installs the pin)"
    files = {}
    for name, digest in pin["sha256"].items():
        data = fetch(RELEASE_URL.format(repo=pin["repo"], version=pin["version"], file=name))
        actual = hashlib.sha256(data).hexdigest()
        if actual != digest:
            raise SystemExit(f"kb: checksum mismatch for {pin['repo']} {pin['version']} {name}: {actual}")
        files[name] = data
    folder.mkdir(parents=True, exist_ok=True)
    for name in ASSETS:
        target = folder / name
        if name in files:
            tmp = folder / f".{name}.tmp"
            tmp.write_bytes(files[name])
            tmp.replace(target)
        elif target.exists():
            target.unlink()  # an asset the pinned release no longer ships
    verb = "installed" if not installed else f"replaced {installed} with"
    return f"{verb} {pin['version']}"


def _read_listing(listing: Path) -> list[str]:
    try:
        enabled = json.loads(listing.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise SystemExit(f"kb: {listing} is not valid JSON: {exc}") from None
    if not isinstance(enabled, list) or not all(isinstance(p, str) for p in enabled):
        raise SystemExit(f"kb: {listing} must be a JSON list of plugin ids")
    return enabled


def _open(uri: str) -> None:
    try:
        if sys.platform == "win32":
            os.startfile(uri)  # noqa: S606 - opening a URI with the default handler
        else:
            opener = "open" if sys.platform == "darwin" else "xdg-open"
            subprocess.Popen([opener, uri], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=child_env())
    except OSError as exc:
        print(f"could not open {uri}: {exc}")


def setup(bundle: Bundle, add: list[str], force: bool = False, open_vault: bool = False, fetch=_download) -> int:
    config = bundle.root / ".obsidian"
    listing = config / "community-plugins.json"
    if not listing.is_file():
        raise SystemExit("kb: kb/.obsidian/community-plugins.json not found; this knowledge base has no Obsidian configuration")
    pins = load_pins(bundle)
    original = _read_listing(listing)
    unknown_add = [p for p in add if p not in pins]
    if unknown_add:
        optional = ", ".join(sorted(p for p, spec in pins.items() if not spec.get("required")))
        raise SystemExit(f"kb: no pin for {', '.join(unknown_add)}; optional plugins: {optional}")
    required = [p for p, spec in pins.items() if spec.get("required") and p not in original]
    enabled = required + original + [p for p in dict.fromkeys(add) if p not in original]
    for plugin in enabled:
        spec = pins.get(plugin)
        if spec is None:
            shown = re.sub(r"[^\w.-]", "?", plugin)
            print(f"{shown}: no pin; install it from Obsidian (Settings → Community plugins)")
            continue
        print(f"{plugin}: {install(config / 'plugins' / plugin, spec, force=force, fetch=fetch)} ({spec['name']}, {spec['license']})")
    if enabled != original:  # only after every download verified
        listing.write_text(json.dumps(enabled, indent=2) + "\n", encoding="utf-8")
        print("updated kb/.obsidian/community-plugins.json")
    print(
        "\nTwo steps are left in Obsidian (they are not stored in the vault):\n"
        "  1. On first open, choose \"Trust author and enable plugins\".\n"
        "  2. Settings → Templater → turn on \"Trigger Templater on new file creation\".\n"
        "Open kb/ as the vault (Open folder as vault), not the repository root."
    )
    if open_vault:
        uri = "obsidian://open?path=" + quote(str(bundle.root), safe="")
        print(f"opening {uri} (works once Obsidian knows the vault; otherwise use Open folder as vault)")
        _open(uri)
    return 0
