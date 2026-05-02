"""
存储瘦身工具（保守模式）

清理目标：
1. storage/runs/inference/ 累积的推理缓存 PNG（同步清空 InferenceResult 表）
2. 每个 task_*/runs/train/weights/epoch*.pt（保留 best.pt + last.pt）
3. 每个 task_*/{raw, cropped, resized}（训练前预处理产物，训练完无用）

保留：
- best.pt / last.pt / results.csv / plots / args.yaml
- dataset/ （YOLO 数据集，万一要复现）
- storage/uploads/ （所有原图）
- venv

用法：
    python tools/cleanup_storage.py            # dry-run，列出将删什么
    python tools/cleanup_storage.py --apply    # 实际删除
"""

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

STORAGE = ROOT / "storage"


def fmt_size(b: int) -> str:
    f = float(b)
    for u in ("B", "KB", "MB", "GB"):
        if f < 1024:
            return f"{f:.1f}{u}"
        f /= 1024
    return f"{f:.1f}TB"


def dir_size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def collect_targets():
    """返回按"组"汇总的清理目标：[(group_name, paths, total_size)]"""
    groups = []

    # 1. inference 缓存
    inf_dir = STORAGE / "runs" / "inference"
    if inf_dir.exists():
        files = [f for f in inf_dir.iterdir() if f.is_file()]
        if files:
            total = sum(f.stat().st_size for f in files)
            groups.append(("推理缓存 (inference/*)", files, total))

    # 2. epoch checkpoints
    runs_dir = STORAGE / "runs"
    if runs_dir.exists():
        epoch_files = []
        for task_dir in sorted(runs_dir.iterdir()):
            if not task_dir.is_dir() or not task_dir.name.startswith("task_"):
                continue
            weights_dir = task_dir / "runs" / "train" / "weights"
            if weights_dir.exists():
                epoch_files.extend(weights_dir.glob("epoch*.pt"))
        if epoch_files:
            total = sum(f.stat().st_size for f in epoch_files)
            groups.append((f"epoch 中间快照 ({len(epoch_files)} 个 .pt)", epoch_files, total))

    # 3. 每个任务的 raw / cropped / resized
    if runs_dir.exists():
        preproc_dirs = []
        for task_dir in sorted(runs_dir.iterdir()):
            if not task_dir.is_dir() or not task_dir.name.startswith("task_"):
                continue
            for sub in ("raw", "cropped", "resized"):
                p = task_dir / sub
                if p.exists() and p.is_dir():
                    preproc_dirs.append(p)
        if preproc_dirs:
            total = sum(dir_size(p) for p in preproc_dirs)
            groups.append((f"训练前预处理产物 ({len(preproc_dirs)} 个目录)", preproc_dirs, total))

    return groups


def cleanup_inference_db() -> int:
    """删除 InferenceResult 记录"""
    from server.database import SessionLocal
    from server.models.inference_result import InferenceResult
    db = SessionLocal()
    try:
        n = db.query(InferenceResult).count()
        if n > 0:
            db.query(InferenceResult).delete()
            db.commit()
        return n
    finally:
        db.close()


def main():
    ap = argparse.ArgumentParser(description="存储瘦身（保守模式）")
    ap.add_argument("--apply", action="store_true", help="实际删除（默认仅 dry-run）")
    args = ap.parse_args()

    groups = collect_targets()
    if not groups:
        print("没有可清理的内容")
        return

    total = 0
    print(f"\n{'分组':<40}{'数量':>10}{'大小':>14}")
    print("-" * 64)
    for name, paths, size in groups:
        print(f"{name:<40}{len(paths):>10}{fmt_size(size):>14}")
        total += size
    print("-" * 64)
    print(f"{'总计释放':<40}{'':>10}{fmt_size(total):>14}\n")

    if not args.apply:
        print("这是 dry-run。确认无误后加 --apply 实际删除：")
        print("  python tools/cleanup_storage.py --apply")
        return

    print("开始删除...")
    deleted_size = 0
    failed = []
    for name, paths, _ in groups:
        for p in paths:
            try:
                size = p.stat().st_size if p.is_file() else dir_size(p)
                if p.is_dir():
                    shutil.rmtree(p)
                else:
                    p.unlink()
                deleted_size += size
            except Exception as e:
                failed.append((p, e))

    print(f"\n文件删除完成：释放 {fmt_size(deleted_size)}")
    if failed:
        print(f"\n失败 {len(failed)} 项：")
        for p, e in failed[:10]:
            print(f"  {p}: {e}")

    print("\n清理 InferenceResult 表...")
    try:
        n = cleanup_inference_db()
        print(f"删除 {n} 条 inference 历史记录")
    except Exception as e:
        print(f"清理 db 失败（非致命）：{e}")


if __name__ == "__main__":
    main()
