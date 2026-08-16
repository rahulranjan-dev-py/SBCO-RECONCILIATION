"""Environment self-check.

Getting the tool running on a locked-down office PC turned out to be the
hardest part of using it, and the failures all looked the same from the user's
side: a command "not recognised", with nothing to say which of six possible
causes it was. This command answers that question in one step, in language a
clerk can read out over the telephone.
"""

from __future__ import annotations

import os
import platform
import shutil
import socket
import sys
from pathlib import Path

PASS, WARN, FAIL = "ok", "check", "problem"

MARK = {PASS: "  [ ok ]  ", WARN: "  [check]  ", FAIL: "  [ !! ]  "}


class Report:
    def __init__(self):
        self.lines = []
        self.worst = PASS

    def add(self, status, title, detail="", fix=""):
        self.lines.append((status, title, detail, fix))
        if status == FAIL or (status == WARN and self.worst == PASS):
            self.worst = status

    def render(self) -> str:
        out = ["", "  SBCO Reconciliation Tool - environment check", ""]
        for status, title, detail, fix in self.lines:
            out.append(f"{MARK[status]}{title}")
            if detail:
                out.append(f"           {detail}")
            if fix:
                for line in fix.split("\n"):
                    out.append(f"           -> {line}")
        out.append("")
        if self.worst == PASS:
            out.append("  Everything needed is in place. Start the tool with:")
            out.append("      python -m sbco_recon.cli gui")
        elif self.worst == WARN:
            out.append("  The tool will run, but see the [check] lines above.")
        else:
            out.append("  Fix the [ !! ] lines above, then run this check again:")
            out.append("      python -m sbco_recon.cli doctor")
        out.append("")
        return "\n".join(out)


def run() -> Report:
    report = Report()

    # ---------------------------------------------------------- interpreter
    version = ".".join(str(n) for n in sys.version_info[:3])
    if sys.version_info >= (3, 9):
        report.add(PASS, f"Python {version}", sys.executable)
    else:
        report.add(FAIL, f"Python {version} is too old",
                   "The tool needs 3.9 or later.",
                   "Install a current Python from python.org/downloads")

    # Windows Store stub: present, named python.exe, but not a real Python
    if platform.system() == "Windows":
        exe = sys.executable.lower()
        if "windowsapps" in exe and "python" not in Path(exe).stem:
            report.add(FAIL, "Windows is routing 'python' to a placeholder",
                       "This is the App Installer stub, not a real Python.",
                       "Open Settings > Apps > Advanced app settings >\n"
                       "App execution aliases. Enable 'Python (default)' and\n"
                       "'Python install manager'. Disable any other python.exe\n"
                       "entry. Then close and reopen Command Prompt.")

    # ------------------------------------------------------------- packages
    try:
        from .. import __version__
        report.add(PASS, f"Reconciliation engine {__version__} is installed")
    except Exception as exc:                                  # pragma: no cover
        report.add(FAIL, "The reconciliation engine is not installed",
                   str(exc),
                   'cd to the tool folder and run:  python -m pip install -e ".[xls]"')

    for module, label, required, why in (
            ("openpyxl", "openpyxl", True, "needed to read and write .xlsx files"),
            ("xlrd", "xlrd", False, "needed only for older .xls downloads"),
    ):
        try:
            __import__(module)
            report.add(PASS, f"{label} is available", why)
        except ImportError:
            if required:
                report.add(FAIL, f"{label} is missing", why,
                           f"python -m pip install {module}")
            else:
                report.add(WARN, f"{label} is not installed", why,
                           f"python -m pip install {module}\n"
                           "Skip this only if all your downloads are .xlsx")

    # ------------------------------------------------------ console shortcut
    if shutil.which("sbco"):
        report.add(PASS, "The 'sbco' shortcut is on your PATH")
    else:
        report.add(WARN, "The 'sbco' shortcut is not on your PATH",
                   "This is normal and harmless.",
                   "Use 'python -m sbco_recon.cli' wherever a guide says 'sbco'.\n"
                   "In the portable package, just double-click SBCO Reconciliation\n"
                   "(the application file), or use sbco.bat for the command line.")

    # ----------------------------------------------------------- data folder
    from ..store import LEGACY_NAME, default_db_path

    try:
        db = default_db_path()
        folder = db.parent
        probe = folder / ".write-test"
        probe.write_text("x", encoding="utf-8")
        probe.unlink()
        if db.exists():
            size = db.stat().st_size / 1024
            report.add(PASS, "Your data file is in place",
                       f"{db}  ({size:,.0f} KB)")
        else:
            report.add(PASS, "Data folder ready; no data file yet",
                       f"{folder}",
                       "It is created the first time the tool runs.")
    except OSError as exc:
        report.add(FAIL, "The data folder cannot be written to", str(exc),
                   "Set SBCO_DATA_DIR to a folder you can write to, for example:\n"
                   "set SBCO_DATA_DIR=D:\\SBCO-data")
        folder = None

    # --------------------------------------------------- pre-2.1 data nearby
    if folder is not None and not (folder / LEGACY_NAME).exists():
        for candidate in (Path.cwd() / LEGACY_NAME,
                          Path(__file__).resolve().parents[3] / LEGACY_NAME):
            if candidate.is_file():
                report.add(WARN, "Data from an older version was found",
                           str(candidate),
                           "It will be carried across automatically the next time\n"
                           "you start the tool. Do not copy it by hand.")
                break

    # ----------------------------------------------------------------- port
    free = None
    for port in range(8765, 8775):
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) != 0:
                free = port
                break
    if free:
        report.add(PASS, "A port is free for the interface", f"127.0.0.1:{free}")
    else:
        report.add(WARN, "Ports 8765-8774 are all in use",
                   "Another copy of the tool may already be running.",
                   "Close it, or start with:  python -m sbco_recon.cli gui --port 8900")

    return report


def main() -> int:
    report = run()
    print(report.render())
    return 0 if report.worst != FAIL else 1
