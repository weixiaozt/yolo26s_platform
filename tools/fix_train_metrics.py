# -*- coding: utf-8 -*-
"""
历史训练任务指标修复
====================
修复两个问题：
1. best_map50 之前是按"历史 mAP50 最高"算的，与 best.pt 实际指标不一致
   → 重新按 fitness 找出真正的 best epoch，同步更新 best_map50 + best_fitness
2. 训练结束后的 final val 会让最后一个 epoch 写两条记录
   → 同 (task_id, epoch) 保留最后写入的（覆盖语义），删除多余的

用法:
  python tools/fix_train_metrics.py              # 处理所有已完成任务
  python tools/fix_train_metrics.py --task 31    # 仅处理某个任务
  python tools/fix_train_metrics.py --dry-run    # 仅预览，不写入
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from server.database import SessionLocal, engine
engine.echo = False

from server.models.train_task import TrainTask, TrainEpochLog


def compute_fitness(map50: float | None, map50_95: float | None) -> float:
    """Ultralytics 默认 fitness 配比"""
    return 0.1 * (map50 or 0) + 0.9 * (map50_95 or 0)


def fix_task(task_id: int, db, dry_run: bool = False) -> dict:
    """
    对单个任务做修复。
    返回字典，键含: task_id, dup_removed, old_best_map50, new_best_map50,
    old_best_fitness, new_best_fitness, best_epoch
    """
    task = db.query(TrainTask).filter(TrainTask.id == task_id).first()
    if not task:
        return {"task_id": task_id, "error": "not found"}

    logs = (
        db.query(TrainEpochLog)
        .filter(TrainEpochLog.task_id == task_id)
        .order_by(TrainEpochLog.epoch, TrainEpochLog.id)
        .all()
    )
    if not logs:
        return {"task_id": task_id, "skipped": "no logs"}

    # ---- 1. 去重：同 epoch 保留最后一条（id 最大），删除前面的 ----
    seen: dict[int, TrainEpochLog] = {}
    to_delete: list[TrainEpochLog] = []
    for l in logs:
        if l.epoch in seen:
            # 保留 id 较大的（最后写入的，对应 final val）
            old = seen[l.epoch]
            if l.id > old.id:
                to_delete.append(old)
                seen[l.epoch] = l
            else:
                to_delete.append(l)
        else:
            seen[l.epoch] = l

    # ---- 2. 用幸存的 logs 找最佳 fitness epoch ----
    surviving = sorted(seen.values(), key=lambda x: x.epoch)
    best_log = max(surviving, key=lambda l: compute_fitness(l.map50_b, l.map50_95_b))
    new_best_fitness = compute_fitness(best_log.map50_b, best_log.map50_95_b)
    new_best_map50 = best_log.map50_b or 0

    result = {
        "task_id": task_id,
        "task_name": task.task_name,
        "status": task.status,
        "logs_total": len(logs),
        "duplicates_to_delete": len(to_delete),
        "best_epoch": best_log.epoch,
        "old_best_map50": task.best_map50,
        "new_best_map50": new_best_map50,
        "old_best_fitness": task.best_fitness,
        "new_best_fitness": new_best_fitness,
    }

    if dry_run:
        return result

    # ---- 3. 应用修改 ----
    for d in to_delete:
        db.delete(d)
    task.best_map50 = new_best_map50
    task.best_fitness = new_best_fitness
    db.commit()

    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", type=int, default=None, help="仅处理某个 task_id")
    parser.add_argument("--dry-run", action="store_true", help="仅预览不写入")
    parser.add_argument("--all", action="store_true", help="处理所有任务（含 cancelled/failed）")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.task:
            tasks = [db.query(TrainTask).filter(TrainTask.id == args.task).first()]
            tasks = [t for t in tasks if t]
        elif args.all:
            tasks = db.query(TrainTask).all()
        else:
            # 默认只处理已完成的任务
            tasks = db.query(TrainTask).filter(TrainTask.status == "completed").all()

        print(f"将处理 {len(tasks)} 个任务" + (" (dry-run)" if args.dry_run else ""))
        print()

        for t in tasks:
            r = fix_task(t.id, db, dry_run=args.dry_run)
            if "error" in r or "skipped" in r:
                print(f"  Task #{r['task_id']}: {r.get('error') or r.get('skipped')}")
                continue
            print(
                f"  Task #{r['task_id']:>3} ({r['task_name']}) "
                f"status={r['status']}"
            )
            print(
                f"    logs={r['logs_total']}, dup_to_delete={r['duplicates_to_delete']}, "
                f"best_epoch={r['best_epoch']}"
            )
            print(
                f"    best_map50: {r['old_best_map50']} -> {r['new_best_map50']:.6f}"
                + (" (CHANGED)" if r['old_best_map50'] != r['new_best_map50'] else "")
            )
            print(
                f"    best_fitness: {r['old_best_fitness']} -> {r['new_best_fitness']:.6f}"
            )
            print()
    finally:
        db.close()


if __name__ == "__main__":
    main()
