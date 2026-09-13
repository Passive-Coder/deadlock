from dataclasses import dataclass, field
from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("DEADLOCK_DATA_DIR", ".deadlock")).resolve())
    database: str = field(default_factory=lambda: os.getenv("DEADLOCK_DATABASE", "sqlite"))
    persistence: float = 2.0
    freshness: float = 2.0
    incident_budget: float = 60.0
    snapshot_interval: float = 0.5
    mediator: str = field(default_factory=lambda: os.getenv("DEADLOCK_MEDIATOR", "codex"))
    roots: list[Path] = field(default_factory=lambda: [Path(p).expanduser().resolve() for p in
        os.getenv("DEADLOCK_WORKSPACE_ROOTS", str(Path.cwd())).split(os.pathsep) if p])

    def __post_init__(self):
        if self.database not in {"sqlite", "exasol"}:
            raise ValueError("DEADLOCK_DATABASE must be sqlite or exasol")
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
