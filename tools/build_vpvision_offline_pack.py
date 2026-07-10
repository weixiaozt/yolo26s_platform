# -*- coding: utf-8 -*-
"""Build a VP-Vision offline deployment package.

The package is designed to be extracted to D:\vp-vision on an offline Windows
machine. Business backend modules under server/ and core/ are shipped as
legacy .pyc files only; third-party packages remain in the bundled venv.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import os
import py_compile
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from urllib.request import urlretrieve


ROOT = Path(__file__).resolve().parent.parent
PYTHON = ROOT / "venv" / "Scripts" / "python.exe"
MARIADB_VERSION = "10.11.18"
MARIADB_ZIP_URL = (
    "https://archive.mariadb.org/"
    f"mariadb-{MARIADB_VERSION}/winx64-packages/mariadb-{MARIADB_VERSION}-winx64.zip"
)
RUNTIME_CACHE = Path(r"D:\vpvision_runtime_cache")
TARGET_PYTHON_HOME = r"D:\vp-vision\runtime\python"


def run(cmd: list[str], cwd: Path = ROOT) -> None:
    print("+", " ".join(cmd))
    subprocess.check_call(cmd, cwd=str(cwd))


def ensure_clean_dir(path: Path) -> None:
    resolved = path.resolve()
    allowed = {Path(r"D:\vp-vision_offline_build").resolve(), Path(r"D:\vp-vision_offline_stage").resolve()}
    if resolved not in allowed:
        raise RuntimeError(f"refuse to clean unexpected path: {resolved}")
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)


def copytree(src: Path, dst: Path, ignore=None) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=ignore)


def compile_backend(app_dir: Path) -> None:
    for package in ("server", "core"):
        src_root = ROOT / package
        for src in src_root.rglob("*.py"):
            rel = src.relative_to(ROOT)
            dst = app_dir / rel.with_suffix(".pyc")
            dst.parent.mkdir(parents=True, exist_ok=True)
            py_compile.compile(
                str(src),
                cfile=str(dst),
                dfile=str(rel).replace("\\", "/"),
                doraise=True,
                optimize=2,
            )


def copy_frontend(app_root: Path) -> None:
    dist = ROOT / "web" / "dist"
    if not dist.exists():
        raise RuntimeError("web/dist does not exist; run npm build first")
    copytree(dist, app_root / "web" / "dist")


def copy_docs(root: Path) -> None:
    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    for name in (
        "vp-vision_offline_deploy_1050ti.md",
        "upgrade_guide.md",
        "离线部署手册.md",
    ):
        src = ROOT / "docs" / name
        if src.exists():
            shutil.copy2(src, docs / name)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.replace("\n", "\r\n"), encoding="utf-8")


def write_runtime_files(root: Path, commit: str) -> None:
    config = root / "config"
    tools = root / "tools"
    logs = root / "logs"
    storage = root / "storage"
    for p in (config, tools, logs, storage / "uploads", storage / "datasets", storage / "runs", storage / "exports"):
        p.mkdir(parents=True, exist_ok=True)

    env_text = """DATABASE_URL=mysql+pymysql://root:123456@127.0.0.1:3307/yolo_seg?charset=utf8mb4
REDIS_URL=redis://127.0.0.1:6379/0
CELERY_BROKER_URL=filesystem://
CELERY_RESULT_BACKEND=rpc://
CELERY_FILESYSTEM_BROKER_DIR=D:\\vp-vision\\storage\\celery-broker
STORAGE_ROOT=D:\\vp-vision\\storage
HOST=0.0.0.0
PORT=8000
DEBUG=False
CORS_ORIGINS=["http://localhost:8000","http://127.0.0.1:8000"]
VPVISION_LICENSE_REQUIRED=True
VPVISION_LICENSE_FILE=D:\\vp-vision\\config\\license.dat
VPVISION_WEB_DIST=D:\\vp-vision\\web\\dist
"""
    write_text(config / ".env", env_text)
    write_text(root / ".env", env_text)

    write_text(
        tools / "init_database.bat",
        """@echo off
setlocal
set BASE=D:\\vp-vision\\runtime\\mariadb
set DATA=D:\\vp-vision\\runtime\\mariadb-data
if exist "%DATA%\\mysql" (
  echo [OK] MariaDB data directory already initialized.
  exit /b 0
)
echo [INFO] Initializing MariaDB data directory...
mkdir "%DATA%" 2>nul
"%BASE%\\bin\\mariadb-install-db.exe" --datadir="%DATA%" --password=123456 --port=3307
if errorlevel 1 (
  echo [ERR] MariaDB initialization failed.
  pause
  exit /b 1
)
echo [OK] MariaDB initialized.
endlocal
""",
    )

    write_text(
        tools / "start_database.bat",
        """@echo off
setlocal
call D:\\vp-vision\\tools\\init_database.bat
if errorlevel 1 exit /b 1
set BASE=D:\\vp-vision\\runtime\\mariadb
set DATA=D:\\vp-vision\\runtime\\mariadb-data
echo [INFO] Starting MariaDB on 127.0.0.1:3307 ...
"%BASE%\\bin\\mariadbd.exe" --defaults-file="%DATA%\\my.ini" --basedir="%BASE%" --datadir="%DATA%" --port=3307 --bind-address=127.0.0.1 --character-set-server=utf8mb4 --collation-server=utf8mb4_unicode_ci --console
endlocal
""",
    )

    write_text(
        tools / "ensure_database.bat",
        """@echo off
setlocal
set BASE=D:\\vp-vision\\runtime\\mariadb
echo [INFO] Waiting for MariaDB...
for /l %%i in (1,1,60) do (
  "%BASE%\\bin\\mariadb-admin.exe" ping -h127.0.0.1 -P3307 -uroot -p123456 --silent >nul 2>nul
  if not errorlevel 1 goto ready
  timeout /t 1 /nobreak >nul
)
echo [ERR] MariaDB did not become ready in time.
pause
exit /b 1
:ready
echo [INFO] Creating database yolo_seg if needed...
"%BASE%\\bin\\mariadb.exe" -h127.0.0.1 -P3307 -uroot -p123456 -e "CREATE DATABASE IF NOT EXISTS yolo_seg DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
if errorlevel 1 (
  echo [ERR] Failed to create/check database.
  pause
  exit /b 1
)
echo [OK] Database ready.
endlocal
""",
    )

    write_text(
        tools / "start_api.bat",
        """@echo off
cd /d D:\\vp-vision
set YOLO_AUTOINSTALL=False
set PYTHONUTF8=1
set PYTHONPATH=D:\\vp-vision\\app
set JWT_SECRET=CHANGE_ME_TO_A_LONG_RANDOM_SECRET
call D:\\vp-vision\\tools\\ensure_database.bat
if errorlevel 1 exit /b 1
D:\\vp-vision\\venv\\Scripts\\python.exe -m uvicorn server.main:app --host 0.0.0.0 --port 8000
pause
""",
    )
    write_text(
        tools / "start_worker.bat",
        """@echo off
cd /d D:\\vp-vision
set YOLO_AUTOINSTALL=False
set PYTHONUTF8=1
set PYTHONPATH=D:\\vp-vision\\app
set JWT_SECRET=CHANGE_ME_TO_A_LONG_RANDOM_SECRET
call D:\\vp-vision\\tools\\ensure_database.bat
if errorlevel 1 exit /b 1
D:\\vp-vision\\venv\\Scripts\\python.exe -m celery -A server.tasks worker --loglevel=info --pool=solo
pause
""",
    )
    write_text(
        tools / "get_machine_code.bat",
        """@echo off
cd /d D:\\vp-vision
D:\\vp-vision\\venv\\Scripts\\python.exe D:\\vp-vision\\tools\\vpvision_get_machine_code.py
pause
""",
    )
    write_text(
        tools / "gpu_check.bat",
        """@echo off
cd /d D:\\vp-vision
D:\\vp-vision\\venv\\Scripts\\python.exe -c "import torch; print('torch:', torch.__version__); print('cuda available:', torch.cuda.is_available()); print('device count:', torch.cuda.device_count()); [print(f'device {i}:', torch.cuda.get_device_name(i), 'capability:', torch.cuda.get_device_capability(i)) for i in range(torch.cuda.device_count())]"
pause
""",
    )
    write_text(
        tools / "smoke_test.bat",
        """@echo off
cd /d D:\\vp-vision
set PYTHONPATH=D:\\vp-vision\\app
set VPVISION_LICENSE_REQUIRED=False
D:\\vp-vision\\venv\\Scripts\\python.exe -c "import server.main; import core.train; print('backend import ok')"
pause
""",
    )
    write_text(
        tools / "start_all.bat",
        """@echo off
cd /d D:\\vp-vision
start "VP-Vision MariaDB" cmd /k D:\\vp-vision\\tools\\start_database.bat
timeout /t 8 /nobreak >nul
call D:\\vp-vision\\tools\\ensure_database.bat
if errorlevel 1 exit /b 1
start "VP-Vision API" cmd /k D:\\vp-vision\\tools\\start_api.bat
timeout /t 5 /nobreak >nul
start "VP-Vision Worker" cmd /k D:\\vp-vision\\tools\\start_worker.bat
echo.
echo VP-Vision is starting. Open http://localhost:8000 after the API window shows startup complete.
pause
""",
    )
    shutil.copy2(ROOT / "tools" / "vpvision_get_machine_code.py", tools / "vpvision_get_machine_code.py")

    write_text(
        root / "README_FIRST.md",
        f"""# VP-Vision 离线部署包

目标目录：`D:\\vp-vision`

版本提交：`{commit}`

先看：`docs\\vp-vision_offline_deploy_1050ti.md`

简要步骤：

1. 解压本包，使目录为 `D:\\vp-vision`。
2. 运行 `tools\\get_machine_code.bat`，把机器码发给管理员。
3. 管理员生成 `license.dat`，放入 `D:\\vp-vision\\config\\license.dat`。
4. 运行 `tools\\gpu_check.bat`，确认 1050Ti CUDA 可用。
5. 运行 `tools\\start_all.bat`。它会启动内置 MariaDB、建库、启动 API 和 Worker。
6. 浏览器打开 `http://localhost:8000`。

本包已内置 MariaDB 10.11 LTS 便携运行时，不要求目标机预装 MySQL/Redis。
""",
    )


def copy_models(root: Path) -> None:
    for pt in ROOT.glob("*.pt"):
        shutil.copy2(pt, root / pt.name)


def copy_venv(root: Path) -> None:
    def ignore(dir_name: str, names: list[str]):
        ignored = {"__pycache__", ".pytest_cache"}
        return {n for n in names if n in ignored or n.endswith((".pyc", ".pyo"))}

    copytree(ROOT / "venv", root / "venv", ignore=ignore)
    (root / "venv" / "pyvenv.cfg").write_text(
        "\n".join(
            [
                f"home = {TARGET_PYTHON_HOME}",
                "include-system-site-packages = false",
                "version = 3.11.15",
                f"executable = {TARGET_PYTHON_HOME}\\python.exe",
                f"command = {TARGET_PYTHON_HOME}\\python.exe -m venv D:\\vp-vision\\venv",
                "",
            ]
        ),
        encoding="utf-8",
    )


def copy_python_runtime(root: Path) -> None:
    pyvenv_cfg = ROOT / "venv" / "pyvenv.cfg"
    base_home = ""
    for line in pyvenv_cfg.read_text(encoding="utf-8").splitlines():
        if line.lower().startswith("home ="):
            base_home = line.split("=", 1)[1].strip()
            break
    if not base_home:
        raise RuntimeError("cannot find base Python home in venv/pyvenv.cfg")
    src = Path(base_home)
    if not (src / "python.exe").exists():
        raise RuntimeError(f"base Python runtime missing: {src}")
    copytree(src, root / "runtime" / "python")


def copy_mariadb_runtime(root: Path) -> None:
    zip_path = RUNTIME_CACHE / f"mariadb-{MARIADB_VERSION}-winx64.zip"
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if not zip_path.exists() or zip_path.stat().st_size < 90_000_000:
        print(f"Downloading MariaDB {MARIADB_VERSION} runtime...")
        urlretrieve(MARIADB_ZIP_URL, zip_path)

    runtime_dir = root / "runtime"
    mariadb_dir = runtime_dir / "mariadb"
    if mariadb_dir.exists():
        shutil.rmtree(mariadb_dir)
    runtime_dir.mkdir(parents=True, exist_ok=True)

    tmp_extract = runtime_dir / "_mariadb_extract"
    if tmp_extract.exists():
        shutil.rmtree(tmp_extract)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(tmp_extract)
    extracted_roots = [p for p in tmp_extract.iterdir() if p.is_dir()]
    if len(extracted_roots) != 1:
        raise RuntimeError(f"unexpected MariaDB zip layout: {extracted_roots}")
    extracted_roots[0].rename(mariadb_dir)
    shutil.rmtree(tmp_extract)


def make_zip(src_root: Path, out_zip: Path) -> None:
    if out_zip.exists():
        out_zip.unlink()
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED, allowZip64=True, compresslevel=6) as zf:
        for path in src_root.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(src_root))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-web-build", action="store_true")
    parser.add_argument("--skip-venv", action="store_true", help="For quick structure tests only; not a real offline package")
    args = parser.parse_args()

    if not PYTHON.exists():
        raise SystemExit(f"missing venv python: {PYTHON}")

    if not args.skip_web_build:
        run(["npm", "run", "build"], cwd=ROOT / "web")

    run([str(PYTHON), "-m", "py_compile", "server/main.py", "core/train.py"])

    commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
    date = dt.datetime.now().strftime("%Y%m%d")
    build_root = Path(r"D:\vp-vision_offline_build")
    stage_root = Path(r"D:\vp-vision_offline_stage")
    ensure_clean_dir(build_root)
    ensure_clean_dir(stage_root)

    target = build_root / "vp-vision"
    app_dir = target / "app"
    app_dir.mkdir(parents=True)
    compile_backend(app_dir)
    copy_frontend(target)
    copy_docs(target)
    write_runtime_files(target, commit)
    copy_mariadb_runtime(target)
    copy_python_runtime(target)
    copy_models(target)
    if args.skip_venv:
        (target / "venv").mkdir()
    else:
        copy_venv(target)

    out_zip = ROOT.parent / f"vp-vision_offline_1050ti_{date}_{commit}.zip"
    make_zip(build_root, out_zip)

    print()
    print(f"OK: {out_zip}")
    print(f"Size: {out_zip.stat().st_size / 1024 / 1024:.2f} MB")
    print(f"SHA256: {sha256(out_zip)}")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)
