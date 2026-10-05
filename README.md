# GPO Halloween Macro

Windows desktop application for recording and replaying keyboard/mouse routes, with OCR-based door checks.

> Use this software only where permitted by the game and platform rules. Automated input can cause unintended in-game actions. Do not run the application as Administrator unless there is a specific, trusted reason.

## Requirements

- Windows 10 or 11
- Python 3.10 or newer to run from source
- Tesseract OCR for door text recognition (install separately)

The application uses Tesseract through `pytesseract`; installing the Python package does **not** install the Tesseract executable. Install Tesseract for Windows, then either add `tesseract.exe` to `PATH` or select its location in the application's OCR settings.

## Run from source

Open PowerShell in the project folder:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python gpo_halloween_macro_prototype.py
```

If PowerShell blocks activation, run the application through the virtual environment directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe gpo_halloween_macro_prototype.py
```

## Build a Windows application

The build creates a folder-based Windows distribution. Python is not required on the recipient's computer; Tesseract is still required for OCR and must be installed separately.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-build.txt
.\build_windows.ps1
```

The distributable application will be in `dist\GPO Halloween Macro\`. Zip that entire folder to share it; do not share only the `.exe`, since it depends on the files beside it.

## First launch

1. Start Roblox and place the game window and UI at the same screen position/resolution used for route recording.
2. Launch the macro and set up the OCR region in Settings. Select the Tesseract executable if it is not on `PATH`.
3. Record a route, add `DOOR` markers at the corresponding interactions, and save the route.
4. Confirm that the configured start, pause, stop, and emergency-stop hotkeys are convenient before playback.
5. Test a route in a safe situation before relying on unattended playback. Stop immediately if the character or camera moves away from the recorded route.

Default hotkeys are F6 (start/resume), F7 (pause), F8 (stop), F9 (mark `DOOR`), F10 (record), and F12 (emergency stop). Hotkeys and timing values can be changed in Settings.

## Local files and privacy

Settings and the default route are stored locally under `%USERPROFILE%\GPO_Halloween_Macro`. Recorded routes contain input actions and timestamps. Review route files before sharing them; they may encode game-specific movement and interaction sequences.

## Tests

```powershell
python -m unittest discover -s tests
```

## License

Released under the MIT License. See [LICENSE](LICENSE).
