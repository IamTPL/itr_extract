import shutil
from pathlib import Path
from uuid import UUID
from config.constants import ECONSENT_FILENAME, INPUT_FILENAME
from config.settings import get_settings

def _files_root() -> Path:
    return get_settings().files_root

def job_dir(user_id: UUID, job_id: UUID) -> Path:
    return _files_root() / str(user_id) / str(job_id)

def _ensure(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path

def write_input(user_id: UUID, job_id: UUID, data: bytes) -> Path:
    p = _ensure(job_dir(user_id, job_id) / INPUT_FILENAME)
    p.write_bytes(data)
    return p

def read_input(user_id: UUID, job_id: UUID) -> bytes:
    return (job_dir(user_id, job_id) / INPUT_FILENAME).read_bytes()

def write_econsent(user_id: UUID, job_id: UUID, data: bytes) -> Path:
    p = _ensure(job_dir(user_id, job_id) / ECONSENT_FILENAME)
    p.write_bytes(data)
    return p

def econsent_path(user_id: UUID, job_id: UUID) -> Path:
    return job_dir(user_id, job_id) / ECONSENT_FILENAME

def input_path(user_id: UUID, job_id: UUID) -> Path:
    return job_dir(user_id, job_id) / INPUT_FILENAME

def delete_job_dir(user_id: UUID, job_id: UUID) -> None:
    d = job_dir(user_id, job_id)
    if d.exists():
        shutil.rmtree(d)

def list_user_dirs() -> list[Path]:
    root = _files_root()
    if not root.exists():
        return []
    return [p for p in root.iterdir() if p.is_dir()]
