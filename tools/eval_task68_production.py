# -*- coding: utf-8 -*-
"""Compare task 65 and task 68 on the 2026-07-27 production-image set."""

import csv
import gc
import json
import sys
import time
from pathlib import Path

import cv2
import torch
from ultralytics import YOLO

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.inference import infer_single_image


ROOT = Path(r"C:\Users\Administrator\Desktop\20260727\20260727")
OUT = Path(r"D:\yolo26s_platform\storage\runs\task_68\production_eval_20260727.csv")
MODELS = {
    65: Path(r"D:\yolo26s_platform\storage\runs\task_65\runs\train\weights\best.pt"),
    68: Path(r"D:\yolo26s_platform\storage\runs\task_68\runs\train\weights\best.pt"),
}
FIELDS = [
    "task_id",
    "relative_path",
    "group",
    "inference_s",
    "num_candidates",
    "max_conf",
    "cls0_max",
    "cls1_max",
    "cls2_max",
    "detections_json",
]


def main() -> None:
    files = sorted(ROOT.rglob("*.bmp"))
    print(f"[start] images={len(files)} output={OUT}", flush=True)
    with OUT.open("w", newline="", encoding="utf-8-sig") as fp:
        writer = csv.DictWriter(fp, fieldnames=FIELDS)
        writer.writeheader()

        for task_id, model_path in MODELS.items():
            print(f"[model] task={task_id} path={model_path}", flush=True)
            model = YOLO(str(model_path), task="segment")
            model_start = time.time()

            for idx, image_path in enumerate(files, 1):
                image = cv2.imread(str(image_path), cv2.IMREAD_UNCHANGED)
                if image is None:
                    print(f"[warn] unreadable {image_path}", flush=True)
                    continue

                started = time.time()
                result = infer_single_image(
                    model,
                    image,
                    crop_size=640,
                    overlap=0.2,
                    conf_thresh=0.01,
                    iou_thresh=0.5,
                    padding=32,
                    resize_size=2048,
                    device="0",
                    use_morphology=True,
                    dilate_kernel=3,
                    erode_kernel=3,
                )
                scores = [float(value) for value in result["scores"]]
                classes = [int(value) for value in result["classes"]]
                boxes = [
                    [round(float(value), 2) for value in box]
                    for box in result["boxes"]
                ]
                detections = [
                    {
                        "class_id": class_id,
                        "confidence": round(score, 6),
                        "box": box,
                    }
                    for class_id, score, box in zip(classes, scores, boxes)
                ]
                class_max = {
                    class_id: max(
                        [
                            score
                            for score, detected_class in zip(scores, classes)
                            if detected_class == class_id
                        ],
                        default=0.0,
                    )
                    for class_id in (0, 1, 2)
                }
                relative_path = image_path.relative_to(ROOT)
                group = relative_path.parts[0] if len(relative_path.parts) > 1 else "误检"

                writer.writerow(
                    {
                        "task_id": task_id,
                        "relative_path": str(relative_path),
                        "group": group,
                        "inference_s": round(time.time() - started, 4),
                        "num_candidates": len(scores),
                        "max_conf": round(max(scores, default=0.0), 6),
                        "cls0_max": round(class_max[0], 6),
                        "cls1_max": round(class_max[1], 6),
                        "cls2_max": round(class_max[2], 6),
                        "detections_json": json.dumps(
                            detections,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                    }
                )
                fp.flush()
                del result, image

                if idx % 20 == 0 or idx == len(files):
                    elapsed = time.time() - model_start
                    print(
                        f"[progress] task={task_id} {idx}/{len(files)} "
                        f"elapsed={elapsed:.1f}s avg={elapsed / idx:.3f}s",
                        flush=True,
                    )

            del model
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            print(
                f"[model-done] task={task_id} "
                f"seconds={time.time() - model_start:.1f}",
                flush=True,
            )
    print("[done]", flush=True)


if __name__ == "__main__":
    main()
