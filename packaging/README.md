# Windows packaging

`make_portable.py` builds the thing end users actually receive: a zip that
extracts to a folder and runs by double-click, with no installer, no admin
rights, and no Python on the PC.

```
SBCO-Reconciliation-<version>-windows-x64/
  SBCO Reconciliation.bat     <- double-click this
  sbco.bat                    <- same tool, command-line form
  README.txt                  <- plain-language notes for the clerk
  runtime/                    <- python.org's embeddable CPython, unmodified,
                                 plus Lib/site-packages with sbco_recon,
                                 openpyxl, xlrd and pyxlsb vendored in
```

## Why this shape

- **No admin rights.** Departmental PCs rarely grant them. Extracting a folder
  needs none.
- **No antivirus quarantine.** Single-file freezers (PyInstaller and friends)
  self-extract at launch and are routinely flagged by endpoint policies. This
  bundle is plain files around a Microsoft-signed `python.exe`.
- **Upgrades cannot destroy data.** The database lives in
  `%LOCALAPPDATA%\SBCO`, never in the program folder, so "delete the folder,
  extract the new one" is the whole upgrade procedure.
- **Deterministic.** Every dependency is pure Python (`py3-none-any` wheels),
  so the same bundle assembles on a Windows, Linux or macOS builder.

## Building

```bash
python packaging/make_portable.py            # downloads the pinned runtime
python packaging/make_portable.py --runtime-zip path/to/python-3.12.8-embed-amd64.zip
```

Output lands in `dist/`: the zip plus `SHA256SUMS.txt`. Pass `--keep-folder`
to also keep the unzipped bundle for inspection.

The embeddable runtime is pinned by version in `make_portable.py`
(`PYTHON_VERSION`), and by SHA-256 once `EXPECTED_SHA256` is set - the builder
prints the computed hash on every run; confirm it against python.org's
published hashes and pin it.

## CI

`.github/workflows/windows.yml` runs the test suite on `windows-latest`
(normal and `-O`), builds the package, and then smoke-tests the **bundled**
runtime - doctor, a file load, a reconciliation, a register entry and a
Table-3 export, all through `runtime\python.exe`, not the runner's Python.
The zip is uploaded as a build artifact on every push, and attached to the
GitHub release when a `v*` tag is pushed.
