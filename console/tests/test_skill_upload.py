import io
import zipfile
from pathlib import Path

import pytest

from app import skill_upload as su

SKILL_MD = """---
name: meteo-test
description: Previsioni di prova
triggers: [meteo]
---
Usa lo strumento per rispondere in una frase.
"""

HTTP_SKILL_MD = """---
name: http-test
description: Chiamata di prova
tools:
  - name: stato
    description: stato
    method: GET
    path: /status
---
Riassumi lo stato.
"""


def make_zip(entries: dict[str, bytes | str], symlink: str | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.external_attr = (0o120777 << 16)   # tipo link simbolico
            zf.writestr(info, "/etc/passwd")
    return buf.getvalue()


def test_valid_instructions_skill_root(tmp_path):
    data = make_zip({"SKILL.md": SKILL_MD})
    r = su.install(data, "meteo-test.zip", tmp_path)
    assert r["name"] == "meteo-test" and r["type"] == "instructions"
    assert (tmp_path / "meteo-test" / "SKILL.md").read_text(encoding="utf-8").startswith("---")


def test_valid_skill_in_single_folder(tmp_path):
    data = make_zip({"cartella/SKILL.md": SKILL_MD, "cartella/README.txt": "x"})
    r = su.install(data, "qualunque.zip", tmp_path)
    assert r["name"] == "cartella"
    assert (tmp_path / "cartella" / "README.txt").exists()


def test_http_skill_is_accepted(tmp_path):
    r = su.install(make_zip({"SKILL.md": HTTP_SKILL_MD}), "http-test.zip", tmp_path)
    assert r["type"] == "http"


@pytest.mark.parametrize("name", ["../evil/SKILL.md", "/abs/SKILL.md", "a\\..\\SKILL.md", "C:/x/SKILL.md"])
def test_path_traversal_rejected(tmp_path, name):
    data = make_zip({"SKILL.md": SKILL_MD, name: "x"})
    with pytest.raises(su.UploadError):
        su.inspect(data, "prova.zip")


def test_symlink_rejected(tmp_path):
    with pytest.raises(su.UploadError, match="link simbolico"):
        su.inspect(make_zip({"SKILL.md": SKILL_MD}, symlink="link"), "prova.zip")


@pytest.mark.parametrize("code", ["tools.py", "scripts/run.sh", "bin/tool.exe"])
def test_code_files_rejected(tmp_path, code):
    data = make_zip({"SKILL.md": HTTP_SKILL_MD, code: "print(1)"})
    with pytest.raises(su.UploadError, match="codice"):
        su.inspect(data, "prova.zip")


def test_python_type_rejected_even_without_py_file(tmp_path):
    md = "---\nname: p\ntype: python\n---\nx\n"
    with pytest.raises(su.UploadError, match="tipo di skill"):
        su.inspect(make_zip({"SKILL.md": md}), "prova.zip")


def test_commands_rejected(tmp_path):
    md = "---\nname: c\ncommands:\n  allow: [ls]\n---\nx\n"
    with pytest.raises(su.UploadError, match="commands"):
        su.inspect(make_zip({"SKILL.md": md}), "prova.zip")


def test_commands_in_local_override_rejected(tmp_path):
    local = "commands:\n  allow: [rm]\n"
    with pytest.raises(su.UploadError, match="commands"):
        su.inspect(make_zip({"SKILL.md": SKILL_MD, "skill.local.yaml": local}), "prova.zip")


def test_missing_skill_md(tmp_path):
    with pytest.raises(su.UploadError, match="SKILL.md non trovato"):
        su.inspect(make_zip({"a/b.txt": "x", "c/d.txt": "y"}), "prova.zip")


def test_zip_bomb_rejected(tmp_path):
    bomb = make_zip({"SKILL.md": SKILL_MD, "big.txt": b"\0" * (3 * 1024 * 1024)})
    with pytest.raises(su.UploadError, match="sospetta"):
        su.inspect(bomb, "prova.zip")


def test_not_a_zip(tmp_path):
    with pytest.raises(su.UploadError, match="zip valido"):
        su.inspect(b"non e' uno zip", "prova.zip")


def test_folder_name_is_sanitized_then_checked(tmp_path):
    # "cartella con spazi" diventa "cartella-con-spazi": valido. Un nome vuoto dopo la pulizia no.
    r = su.inspect(make_zip({"cartella con spazi/SKILL.md": SKILL_MD}), "prova.zip")
    assert r["folder"] == "cartella-con-spazi"
    with pytest.raises(su.UploadError, match="nome"):
        su.inspect(make_zip({"___/SKILL.md": SKILL_MD}), "prova.zip")


def test_existing_skill_is_not_overwritten(tmp_path):
    su.install(make_zip({"SKILL.md": SKILL_MD}), "meteo-test.zip", tmp_path)
    with pytest.raises(su.UploadError, match="esiste gia"):
        su.install(make_zip({"SKILL.md": SKILL_MD}), "meteo-test.zip", tmp_path)


def test_failed_install_leaves_no_staging(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise OSError("disco pieno")
    monkeypatch.setattr(su.os, "replace", boom)
    with pytest.raises(OSError):
        su.install(make_zip({"SKILL.md": SKILL_MD}), "meteo-test.zip", tmp_path)
    assert not any(p.name.startswith(".staging-") for p in tmp_path.iterdir())
    assert not (tmp_path / "meteo-test").exists()
