# -*- coding: utf-8 -*-
"""打全量更新包给同事电脑（无 .git 的部署）解压覆盖用。

包含：
- 所有 git tracked 的文件（自动遵循 .gitignore）
- 还没 commit 的新增文档（如 docs/upgrade_guide.md）

不包含：
- venv / node_modules / storage / .env / *.pt / *.zip / *.log / __pycache__
  （已由 .gitignore 排除）
- mask2png.py / CLAUDE.md（untracked 用户私有文件）

输出：D:\yolo26s_update_<HEAD短hash>_<日期>.zip
"""
import subprocess
import zipfile
import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 1. git tracked 文件
tracked = subprocess.check_output(
    ["git", "ls-files"], cwd=str(ROOT), text=True, encoding="utf-8"
).splitlines()
tracked = [l.strip() for l in tracked if l.strip()]

# 2. 还没 commit 的新文件（手动加入，保证升级包里有最新指南和工具）
extras = [
    "docs/upgrade_guide.md",
    "tools/update_from_github.bat",   # 同事 git 转化后可用的一键升级脚本
    "tools/update_simple.bat",        # 精简版
]
for e in extras:
    if (ROOT / e).exists() and e not in tracked:
        tracked.append(e)

# 3. 排除自身（这个脚本本身不需要给同事，但放进去也无妨）
# 这里保留进 zip，作为以后同事自己打包的工具

# 4. HEAD 短 hash + 日期作为文件名
head = subprocess.check_output(
    ["git", "rev-parse", "--short", "HEAD"], cwd=str(ROOT), text=True
).strip()
date_str = datetime.datetime.now().strftime("%Y%m%d")
out_zip = ROOT.parent / f"yolo26s_update_{date_str}_{head}.zip"

# 5. 打包
missing = []
written = 0
with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
    for rel in tracked:
        src = ROOT / rel
        if not src.exists():
            missing.append(rel)
            continue
        zf.write(str(src), rel)
        written += 1

    # 在 zip 顶层加一个 README.txt 指向升级指南
    readme = f"""yolo26s_platform 更新包
========================

打包时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
HEAD commit: {head}
文件数: {written}

升级步骤详见解压后的 docs/upgrade_guide.md
关键步骤摘要：
  1. 关掉 uvicorn / celery / vite（任务管理器 kill python.exe）
  2. 把本 zip 解压到 D:\\yolo26s_platform\\，全部覆盖
  3. 启动 uvicorn（会自动跑数据库迁移）
  4. 启动 celery + 前端
  5. 浏览器 Ctrl+F5 强刷

不影响（zip 里没这些，所以解压不会动它们）：
  - storage/  数据 / 模型
  - .env      配置
  - venv      Python 环境
  - web/node_modules  前端依赖
"""
    zf.writestr("README_FIRST.txt", readme)

size_mb = out_zip.stat().st_size / 1024 / 1024
print(f"\nOK: {written} files, {size_mb:.2f} MB")
print(f"-> {out_zip}")
if missing:
    print(f"\n[skip] missing {len(missing)} files (git-tracked but not on disk):")
    for m in missing[:20]:
        print(f"  - {m}")
    if len(missing) > 20:
        print(f"  ... 还有 {len(missing) - 20} 个")
