import os
import shutil

from pathlib import Path

os.system(f"uv run package.py --name blive_queue --windowed --icon static/logo.ico main.py")

shutil.copytree("static", Path("dist", "blive_queue", "static"), dirs_exist_ok=True)