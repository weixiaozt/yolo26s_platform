"""
分类模型推理验证：用训练集全量跑一遍，得到混淆矩阵和总准确率。

用法：
    python tools/verify_cls.py <best_pt_path>
"""
import sys
from collections import defaultdict
from pathlib import Path

# 让脚本能 import server.*
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ultralytics import YOLO
from server.database import SessionLocal
from server.models.image import Image
from server.models.defect_class import DefectClass
from server.config import settings


def main():
    if len(sys.argv) < 2:
        print("用法: python verify_cls.py <best_pt_path>")
        sys.exit(1)
    best_pt = sys.argv[1]
    project_id = int(sys.argv[2]) if len(sys.argv) > 2 else 26

    print(f"加载模型: {best_pt}")
    model = YOLO(best_pt)
    print(f"模型类别: {model.names}")

    db = SessionLocal()
    classes = db.query(DefectClass).filter(DefectClass.project_id == project_id).all()
    cid_to_name = {dc.id: dc.name for dc in classes}
    print(f"项目类别: {cid_to_name}")

    images = (
        db.query(Image)
        .filter(Image.project_id == project_id, Image.class_id.isnot(None))
        .all()
    )
    print(f"待验证图片: {len(images)} 张\n")

    correct = 0
    total = 0
    confusion: dict = defaultdict(lambda: defaultdict(int))

    for img in images:
        fp = Path(img.file_path)
        if not fp.is_absolute():
            fp = settings.upload_path / img.file_path
        if not fp.exists():
            continue
        gt_name = cid_to_name.get(img.class_id)
        if not gt_name:
            continue
        result = model.predict(str(fp), verbose=False)[0]
        pred_idx = int(result.probs.top1)
        pred_name = result.names[pred_idx]
        confusion[gt_name][pred_name] += 1
        if pred_name == gt_name:
            correct += 1
        total += 1
        if total % 200 == 0:
            print(f"  进度 {total}/{len(images)}  当前 acc={correct/total:.3f}")

    print(f"\n{'='*50}")
    print(f"总数: {total}   正确: {correct}   准确率: {correct/total:.4f}")
    print(f"{'='*50}")
    print("\n混淆矩阵 (行=真实, 列=预测):")
    all_classes = sorted(set(list(confusion.keys()) + [n for d in confusion.values() for n in d]))
    header = "  GT \\ Pred  | " + " | ".join(f"{c:>8s}" for c in all_classes) + " |   总数 |  召回"
    print(header)
    print("-" * len(header))
    for gt in all_classes:
        row_total = sum(confusion[gt].values())
        recall = confusion[gt].get(gt, 0) / row_total if row_total else 0
        cells = " | ".join(f"{confusion[gt].get(c, 0):>8d}" for c in all_classes)
        print(f"  {gt:>10s} | {cells} | {row_total:>6d} | {recall:.3f}")

    print("\n精确率（列方向）:")
    for c in all_classes:
        col_total = sum(confusion[gt].get(c, 0) for gt in all_classes)
        precision = confusion.get(c, {}).get(c, 0) / col_total if col_total else 0
        print(f"  {c}: precision={precision:.3f} ({confusion.get(c,{}).get(c,0)}/{col_total})")

    db.close()


if __name__ == "__main__":
    main()
