import os
from pathlib import Path


def data_path(filename: str) -> Path:
    candidates: list[Path] = []
    env_dir = os.getenv("GAME_DATA_DIR")
    if env_dir:
        candidates.append(Path(env_dir))

    here = Path(__file__).resolve()
    candidates.extend([
        Path.cwd() / "data",
        Path.cwd() / "src" / "data",
        here.parents[2] / "data",
        here.parents[3] / "data",
        here.parents[3] / "src" / "data",
    ])

    checked = []
    for base in candidates:
        path = (base / filename).resolve()
        checked.append(str(path))
        if path.exists():
            return path
    raise FileNotFoundError(f"Data file {filename!r} not found. Checked: {', '.join(checked)}")
