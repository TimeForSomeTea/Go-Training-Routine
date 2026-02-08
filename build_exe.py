import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SCRIPT_NAME = "Go_Training_Session.py"
APP_NAME = "Go_Training_Session"


def ensure_pyinstaller():
    try:
        import PyInstaller  # noqa: F401
    except ModuleNotFoundError:
        print("PyInstaller not found. Installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])


def clean_previous_build():
    for path in (PROJECT_ROOT / "build", PROJECT_ROOT / "dist"):
        if path.exists():
            shutil.rmtree(path)
    spec_file = PROJECT_ROOT / f"{APP_NAME}.spec"
    if spec_file.exists():
        spec_file.unlink()


def build_executable():
    script_path = PROJECT_ROOT / SCRIPT_NAME
    if not script_path.exists():
        raise FileNotFoundError(f"Could not find {SCRIPT_NAME} in {PROJECT_ROOT}")

    ensure_pyinstaller()
    clean_previous_build()

    subprocess.check_call(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--onefile",
            "--name",
            APP_NAME,
            "--noconfirm",
            "--clean",
            str(script_path),
        ],
        cwd=PROJECT_ROOT,
    )

    exe_suffix = ".exe" if os.name == "nt" else ""
    output_path = PROJECT_ROOT / "dist" / f"{APP_NAME}{exe_suffix}"
    print(f"Build complete: {output_path}")


if __name__ == "__main__":
    build_executable()
