from uuid import uuid4
import pytest
from storage import files as fs
from config.constants import INPUT_FILENAME, ECONSENT_FILENAME

def test_job_dir_segregates_user(tmp_path, monkeypatch):
    monkeypatch.setattr(fs, "_files_root", lambda: tmp_path)
    u, j = uuid4(), uuid4()
    d = fs.job_dir(u, j)
    assert d == tmp_path / str(u) / str(j)

def test_write_input_then_read(tmp_path, monkeypatch):
    monkeypatch.setattr(fs, "_files_root", lambda: tmp_path)
    u, j = uuid4(), uuid4()
    fs.write_input(u, j, b"hello")
    assert fs.read_input(u, j) == b"hello"

def test_delete_job_dir_removes_tree(tmp_path, monkeypatch):
    monkeypatch.setattr(fs, "_files_root", lambda: tmp_path)
    u, j = uuid4(), uuid4()
    fs.write_input(u, j, b"x")
    fs.write_econsent(u, j, b"y")
    fs.delete_job_dir(u, j)
    assert not fs.job_dir(u, j).exists()

def test_econsent_uses_constant_filename(tmp_path, monkeypatch):
    monkeypatch.setattr(fs, "_files_root", lambda: tmp_path)
    u, j = uuid4(), uuid4()
    fs.write_econsent(u, j, b"y")
    assert (fs.job_dir(u, j) / ECONSENT_FILENAME).exists()

def test_input_uses_constant_filename(tmp_path, monkeypatch):
    monkeypatch.setattr(fs, "_files_root", lambda: tmp_path)
    u, j = uuid4(), uuid4()
    fs.write_input(u, j, b"x")
    assert (fs.job_dir(u, j) / INPUT_FILENAME).exists()
