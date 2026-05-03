"""回填 cls 训练任务的 epoch 指标。

之前 server/tasks/train_task.py 的 epoch_callback 漏写了 top1_acc/top5_acc，
也没把 cls 的 train/val_loss 落到 train_cls_loss/val_cls_loss 列，
导致历史 cls 任务的训练监控图全空。

本脚本扫描所有 task_type=cls 的训练任务，从 results.csv 读取数据回填到
train_epoch_logs 表。安全幂等（仅在列为 NULL 时才填写）。

用法：
    python tools/backfill_cls_epochs.py            # 回填所有 cls 任务
    python tools/backfill_cls_epochs.py --task 38  # 仅回填指定任务
    python tools/backfill_cls_epochs.py --dry-run  # 仅打印不写库
"""
import argparse
import sys
from pathlib import Path

import pandas as pd

# 把项目根目录加入 sys.path，使 server.* 可以 import
sys.path.insert(0, str(Path(__file__).parent.parent))

from server.database import SessionLocal  # noqa: E402
from server.models.train_task import TrainTask, TrainEpochLog  # noqa: E402
from server.models.project import Project  # noqa: E402


def backfill_one(db, task: TrainTask, dry: bool) -> int:
    """回填单个训练任务，返回写入的 epoch 行数。"""
    if not task.output_dir:
        print(f"  [skip] task #{task.id}: output_dir 为空")
        return 0

    csv_path = Path(task.output_dir) / "runs" / "train" / "results.csv"
    if not csv_path.exists():
        print(f"  [skip] task #{task.id}: {csv_path} 不存在")
        return 0

    df = pd.read_csv(csv_path)
    df.columns = df.columns.str.strip()

    # cls 必备列
    required = ["epoch", "train/loss", "val/loss", "metrics/accuracy_top1"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        print(f"  [skip] task #{task.id}: results.csv 缺列 {missing}")
        return 0

    n_written = 0
    for _, row in df.iterrows():
        # CSV epoch 从 1 开始，DB 用 0-based
        ep = int(row["epoch"]) - 1
        log = (
            db.query(TrainEpochLog)
            .filter(TrainEpochLog.task_id == task.id, TrainEpochLog.epoch == ep)
            .first()
        )
        if log is None:
            log = TrainEpochLog(task_id=task.id, epoch=ep)
            db.add(log)

        # 仅填空列
        if log.train_cls_loss is None and "train/loss" in row:
            log.train_cls_loss = float(row["train/loss"])
        if log.val_cls_loss is None and "val/loss" in row:
            log.val_cls_loss = float(row["val/loss"])
        if log.top1_acc is None and "metrics/accuracy_top1" in row:
            log.top1_acc = float(row["metrics/accuracy_top1"])
        if log.top5_acc is None and "metrics/accuracy_top5" in row:
            log.top5_acc = float(row["metrics/accuracy_top5"])
        if log.lr is None and "lr/pg0" in row:
            log.lr = float(row["lr/pg0"])

        n_written += 1

    if not dry:
        db.commit()
    else:
        db.rollback()
    return n_written


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", type=int, help="仅回填指定 task_id")
    ap.add_argument("--dry-run", action="store_true", help="仅打印不写库")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        # 找出所有 cls 任务
        q = (
            db.query(TrainTask)
            .join(Project, Project.id == TrainTask.project_id)
            .filter(Project.task_type == "cls")
        )
        if args.task:
            q = q.filter(TrainTask.id == args.task)

        tasks = q.all()
        if not tasks:
            print("(没有匹配的 cls 训练任务)")
            return

        print(f"找到 {len(tasks)} 个 cls 训练任务")
        total_written = 0
        for t in tasks:
            print(f"\n[task #{t.id}] {t.task_name}  status={t.status}")
            n = backfill_one(db, t, args.dry_run)
            print(f"  写入 {n} 个 epoch 行" + ("（dry-run，未提交）" if args.dry_run else ""))
            total_written += n

        print(f"\n总计：{total_written} 行")
    finally:
        db.close()


if __name__ == "__main__":
    main()
