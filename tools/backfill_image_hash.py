# -*- coding: utf-8 -*-
"""
backfill_image_hash.py — 给存量图片补 content_hash（图片字节 sha256）
====================================================================

「合并标注包」功能按 content_hash 匹配两台机器上的"同一张图"。新上传/新导入的图
会自动算哈希，但本功能上线前的存量图 content_hash 为空。在每台要参与合并的机器上
各跑一次本脚本补齐即可（合并时也会对缺哈希的图现场兜底计算，但提前补好更快更稳）。

用法（项目根目录）：
    D:/yolo26s_platform/venv/Scripts/python.exe tools/backfill_image_hash.py
    # 只统计不写库：
    D:/yolo26s_platform/venv/Scripts/python.exe tools/backfill_image_hash.py --dry-run
"""
import sys
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.database import SessionLocal          # noqa: E402
from server.config import settings                # noqa: E402
from server.models.image import Image             # noqa: E402


def sha256_file(path: Path):
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def main():
    dry = "--dry-run" in sys.argv
    db = SessionLocal()
    upload_root = settings.upload_path
    try:
        imgs = db.query(Image).filter(Image.content_hash.is_(None)).all()
        tag = "（dry-run，不写库）" if dry else ""
        print(f"待补哈希图片：{len(imgs)} 张{tag}")
        done = missing = 0
        for i, img in enumerate(imgs, 1):
            h = sha256_file(upload_root / img.file_path)
            if h is None:
                missing += 1
                print(f"  [缺文件] id={img.id} {img.file_path}")
                continue
            if not dry:
                img.content_hash = h
            done += 1
            if i % 200 == 0:
                print(f"  ...{i}/{len(imgs)}")
                if not dry:
                    db.commit()
        if not dry:
            db.commit()
        print(f"完成：补哈希 {done} 张，缺文件 {missing} 张。")
    finally:
        db.close()


if __name__ == "__main__":
    main()
