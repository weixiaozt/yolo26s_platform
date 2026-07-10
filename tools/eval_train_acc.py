# -*- coding: utf-8 -*-
"""
等指定训练任务完成 → 用 best.pt 对 ImageFolder 数据集做推理 → 报告训练/验证准确率。

输出三个文件（路径见常量）：
  - PROGRESS_LOG  追加日志（每行带时间戳）
  - REPORT_JSON   最终报告（JSON，便于后续解析）
  - DONE_FLAG     完成标志（"done" / "failed" / "error"）

用户验收：训练图准确率 >= 99.6%
"""
import os
import sys
import time
import json
import traceback
from pathlib import Path
from datetime import datetime
from collections import Counter, defaultdict

import requests

BASE = "http://127.0.0.1:8000"
TASK_ID = int(os.environ.get("EVAL_TASK_ID", "44"))
THRESHOLD = float(os.environ.get("EVAL_THRESHOLD", "0.996"))

TMP = Path(r"C:\Users\Administrator\AppData\Local\Temp")
PROGRESS_LOG = TMP / f"eval_task{TASK_ID}_progress.log"
REPORT_JSON  = TMP / f"eval_task{TASK_ID}_report.json"
DONE_FLAG    = TMP / f"eval_task{TASK_ID}_done.flag"


def log(msg: str) -> None:
    line = f"[{datetime.now():%H:%M:%S}] {msg}"
    print(line, flush=True)
    with PROGRESS_LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def main() -> int:
    PROGRESS_LOG.write_text("", encoding="utf-8")
    for f in (REPORT_JSON, DONE_FLAG):
        if f.exists():
            f.unlink()

    s = requests.Session()
    r = s.post(f"{BASE}/api/auth/login", json={"username": "admin", "password": "admin123"})
    r.raise_for_status()
    tok = r.json()
    s.headers["Authorization"] = f"Bearer {tok.get('access_token') or tok.get('token')}"

    log(f"polling task {TASK_ID} (threshold={THRESHOLD*100:.2f}%)")
    last_line = ""
    while True:
        try:
            r = s.get(f"{BASE}/api/train/tasks/{TASK_ID}", timeout=10)
            r.raise_for_status()
        except Exception as e:
            log(f"  poll error: {e}, retrying in 30s")
            time.sleep(30)
            continue
        t = r.json()
        status = t["status"]
        ep = t.get("current_epoch") or 0
        total = t.get("epochs") or 0
        best = t.get("best_map50") or t.get("best_fitness")
        cur = f"status={status} epoch={ep}/{total} best={best}"
        if cur != last_line:
            log(cur)
            last_line = cur
        if status in ("completed", "failed", "cancelled"):
            break
        time.sleep(30)

    if status != "completed":
        report = {"ok": False, "reason": status, "error": t.get("error_message")}
        REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        DONE_FLAG.write_text("failed", encoding="utf-8")
        log(f"training {status}, exiting")
        return 1

    best_pt = t["best_model_path"]
    out_dir = Path(t["output_dir"])
    log(f"output_dir = {out_dir}")
    log(f"best_pt    = {best_pt}")

    os.environ.setdefault("YOLO_AUTOINSTALL", "False")
    sys.path.insert(0, r"D:\yolo26s_platform")
    from ultralytics import YOLO  # noqa: E402

    model = YOLO(best_pt)
    log(f"model.names = {dict(model.names)}")

    IMG_EXTS = {".bmp", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}
    dataset_root = out_dir / "dataset"

    def collect(split_dir: Path):
        items: list[tuple[Path, str]] = []
        if not split_dir.exists():
            return items
        for cls_dir in sorted(split_dir.iterdir()):
            if not cls_dir.is_dir():
                continue
            for p in cls_dir.iterdir():
                if p.is_file() and p.suffix.lower() in IMG_EXTS:
                    items.append((p, cls_dir.name))
        return items

    train_items = collect(dataset_root / "train")
    val_items = collect(dataset_root / "val")
    log(f"collected: train={len(train_items)} val={len(val_items)}")

    if not train_items:
        report = {"ok": False, "reason": "no_train_images", "dataset_root": str(dataset_root)}
        REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        DONE_FLAG.write_text("error", encoding="utf-8")
        log(f"no training images under {dataset_root}/train")
        return 2

    def evaluate(items, label: str):
        if not items:
            return None
        correct = 0
        per_cls_total: Counter = Counter()
        per_cls_ok: Counter = Counter()
        confusion: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        errors: list[dict] = []
        BS = 64
        for i in range(0, len(items), BS):
            batch = items[i:i + BS]
            paths = [str(p) for p, _ in batch]
            preds = model.predict(paths, imgsz=224, verbose=False, device=0)
            for (p, gt), pr in zip(batch, preds):
                pred_idx = int(pr.probs.top1)
                pred_name = model.names[pred_idx]
                pred_conf = float(pr.probs.top1conf)
                per_cls_total[gt] += 1
                if pred_name == gt:
                    per_cls_ok[gt] += 1
                    correct += 1
                else:
                    if len(errors) < 100:
                        try:
                            rel = str(p.relative_to(dataset_root)).replace("\\", "/")
                        except ValueError:
                            rel = p.name
                        errors.append({
                            "file": p.name, "rel": rel,
                            "gt": gt, "pred": pred_name,
                            "conf": round(pred_conf, 4),
                        })
                confusion[gt][pred_name] += 1
            if (i // BS) % 10 == 0:
                log(f"  {label}: {i + len(batch)}/{len(items)} ok={correct}")
        acc = correct / len(items)
        per_class = []
        for cname in sorted(per_cls_total.keys()):
            n = per_cls_total[cname]
            c = per_cls_ok[cname]
            per_class.append({"class": cname, "total": n, "correct": c, "wrong": n - c,
                              "acc": round(c / n, 6) if n else 0.0})
        return {
            "total": len(items),
            "correct": correct,
            "wrong": len(items) - correct,
            "accuracy": round(acc, 6),
            "per_class": per_class,
            "confusion": {gt: dict(d) for gt, d in confusion.items()},
            "error_samples": errors,
        }

    train_res = evaluate(train_items, "train")
    val_res = evaluate(val_items, "val")

    train_pass = bool(train_res and train_res["accuracy"] >= THRESHOLD)
    report = {
        "ok": True,
        "task_id": TASK_ID,
        "best_pt": best_pt,
        "output_dir": str(out_dir),
        "model_names": dict(model.names),
        "threshold": THRESHOLD,
        "train": train_res,
        "val": val_res,
        "pass": train_pass,
    }
    REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    DONE_FLAG.write_text("done", encoding="utf-8")

    val_acc = val_res["accuracy"] if val_res else 0.0
    log(f"REPORT: train_acc={train_res['accuracy']*100:.3f}% "
        f"val_acc={val_acc*100:.3f}% pass={train_pass}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log(f"FATAL: {e}")
        log(traceback.format_exc())
        REPORT_JSON.write_text(
            json.dumps({"ok": False, "reason": "exception", "error": str(e),
                        "trace": traceback.format_exc()}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        DONE_FLAG.write_text("error", encoding="utf-8")
        sys.exit(2)
