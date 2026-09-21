"""Build or verify a shareable viewer ZIP using only PACKAGE_FILES.txt."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys
import zipfile

ROOT = Path(__file__).resolve().parent
ARCHIVE_ROOT = "Microduck-IMU-viewer"
ALLOWLIST = "PACKAGE_FILES.txt"
MANIFEST = "PACKAGE-MANIFEST.json"
TEMPLATE = "tools/servo-web-imu/config.example.json"
CONFIG = "tools/servo-web-imu/config.json"
FORBIDDEN_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules", "logs",
                  "runtime-temp", "pip-cache", "dist", ".pytest_cache", ".mypy_cache"}
FORBIDDEN_SUFFIXES = {".zip", ".exe", ".dll", ".axf", ".o", ".obj", ".pdb", ".pyc",
                      ".pyo", ".log", ".uvoptx", ".uvguix", ".uvguixx", ".tmp"}
REQUIRED = {"README.md", "VALIDATION.md", "package.py", ALLOWLIST, ".gitignore",
            ".gitattributes", TEMPLATE}


def safe_relative(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if (not name or name != path.as_posix() or path.is_absolute()
            or any(part in (".", "..") for part in path.parts)
            or "\\" in name or ":" in name or any(char in name for char in "*?[]\x00\r\n")):
        raise ValueError(f"Unsafe or nonliteral package path: {name!r}")
    return path


def read_allowlist(text: str) -> list[str]:
    names = [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    if len(names) != len(set(names)):
        raise ValueError("Duplicate file in PACKAGE_FILES.txt")
    for name in names:
        path = safe_relative(name)
        lower_parts = {part.lower() for part in path.parts}
        if (lower_parts & FORBIDDEN_DIRS or path.suffix.lower() in FORBIDDEN_SUFFIXES
                or path.name.lower() in {"config.json", MANIFEST.lower()}
                or path.name.lower().startswith(".env")):
            raise ValueError(f"Private or generated file must not be allowlisted: {name}")
        if "build" in lower_parts and name not in {
            "firmware/imu_to_dxl/Build/imu_to_dxl.bin",
            "firmware/imu_to_dxl/Build/imu_to_dxl.hex",
            "firmware/imu_to_dxl/Build/imu_to_dxl.map",
        }:
            raise ValueError(f"Only the validated bin/hex/map may be packaged from Build: {name}")
    if missing := REQUIRED - set(names):
        raise ValueError(f"Required package files are not allowlisted: {', '.join(sorted(missing))}")
    return sorted(names)


def canonical_payload(name: str, data: bytes) -> bytes:
    if name.lower().endswith(".cmd"):
        # CMD can corrupt UTF-8 text with LF-only lines, especially in nested calls.
        text = data.decode("ascii")
        data = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n").encode("ascii")
    return data


def template_config(data: bytes) -> bytes:
    config = json.loads(data.decode("utf-8-sig"))
    if not isinstance(config, dict) or config.get("probe_serial", "missing") is not None:
        raise ValueError("config.example.json must contain probe_serial: null; never share a personal probe identity.")
    return data


def source_payloads() -> dict[str, bytes]:
    names = read_allowlist((ROOT / ALLOWLIST).read_text(encoding="utf-8-sig"))
    files = {}
    for name in names:
        source = ROOT.joinpath(*PurePosixPath(name).parts)
        if not source.is_file():
            raise ValueError(f"Allowlisted file is missing: {name}")
        if not source.resolve().is_relative_to(ROOT):
            raise ValueError(f"Allowlisted file escapes the project directory: {name}")
        if any(part.is_symlink() for part in (source, *source.parents) if part != ROOT.parent):
            raise ValueError(f"Symbolic links are not packaged: {name}")
        files[name] = canonical_payload(name, source.read_bytes())
    files[CONFIG] = template_config(files[TEMPLATE])
    return files


def make_manifest(files: dict[str, bytes]) -> bytes:
    payload = {
        "schema_version": 1,
        "archive_root": ARCHIVE_ROOT,
        "generated_files": [CONFIG],
        "notes": "SHA256 covers each packaged file except this manifest. Hashes detect corruption; they do not authenticate the author.",
        "files": [{"path": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                  for name, data in sorted(files.items())],
    }
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def verify_archive(path: Path) -> int:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Archive has duplicate members")
        prefix = ARCHIVE_ROOT + "/"
        for info in archive.infolist():
            if not info.filename.startswith(prefix) or info.is_dir():
                raise ValueError(f"Unexpected archive member: {info.filename}")
            safe_relative(info.filename[len(prefix):])
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("Archive must not contain symbolic links")
        allowlist = read_allowlist(archive.read(prefix + ALLOWLIST).decode("utf-8-sig"))
        expected = set(allowlist) | {CONFIG, MANIFEST}
        actual = {name[len(prefix):] for name in names}
        if actual != expected:
            raise ValueError("Archive members do not match the explicit allowlist and generated files")
        manifest = json.loads(archive.read(prefix + MANIFEST))
        if manifest.get("schema_version") != 1 or manifest.get("archive_root") != ARCHIVE_ROOT:
            raise ValueError("Unsupported manifest format")
        records = manifest.get("files", [])
        listed = [record["path"] for record in records]
        if len(listed) != len(set(listed)) or set(listed) != expected - {MANIFEST}:
            raise ValueError("Manifest does not cover exactly the packaged files")
        for record in records:
            data = archive.read(prefix + record["path"])
            if len(data) != record["size"] or hashlib.sha256(data).hexdigest() != record["sha256"]:
                raise ValueError(f"Manifest mismatch: {record['path']}")
            if canonical_payload(record["path"], data) != data:
                raise ValueError(f"CMD must use ASCII and CRLF: {record['path']}")
        if archive.read(prefix + CONFIG) != template_config(archive.read(prefix + TEMPLATE)):
            raise ValueError("Generated config.json differs from the public example")
    return len(records)


def build_archive(output: Path) -> int:
    files = source_payloads()
    files[MANIFEST] = make_manifest(files)
    output = output.resolve()
    if output.is_relative_to(ROOT) and output.relative_to(ROOT).as_posix() in files:
        raise ValueError("Output would overwrite a package source file")
    output.parent.mkdir(parents=True, exist_ok=True)
    # Fixed timestamps, order, permissions, and JSON make unchanged sources reproducible.
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(f"{ARCHIVE_ROOT}/{name}", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data, compresslevel=9)
    return verify_archive(output)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / f"{ARCHIVE_ROOT}.zip")
    parser.add_argument("--verify", type=Path, help="Verify an existing ZIP without building or extracting it")
    args = parser.parse_args(argv)
    try:
        if args.verify:
            count = verify_archive(args.verify)
            print(f"Verified {count} file hashes: {args.verify.resolve()}")
        else:
            count = build_archive(args.output)
            print(f"Packaged and verified {count} files: {args.output.resolve()}")
            print("Personal config.json, virtual environments, caches, and logs were not copied.")
        return 0
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        print(f"Packaging failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
