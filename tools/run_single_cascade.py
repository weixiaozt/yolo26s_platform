"""Run one image through the validated task68 -> task73 OpenVINO cascade."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("YOLO_AUTOINSTALL", "False")

from core.inference import infer_single_image  # noqa: E402
from server.routers.inference import _crop_defect_for_classifier  # noqa: E402


STAGE1_NAMES = {0: "Crack", 1: "EdgeChip", 2: "Notch"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--seg-model",
        type=Path,
        default=PROJECT_ROOT / "storage/runs/task_68/runs/train/weights/best_openvino_model/best.xml",
    )
    parser.add_argument(
        "--cls-model",
        type=Path,
        default=PROJECT_ROOT / "storage/runs/cascade_classifier_20260729/closedset_4class_nano_v2_20260729/nano_4class/weights/best_openvino_model/best.xml",
    )
    parser.add_argument("--ok-threshold", type=float, default=0.7)
    return parser.parse_args()


def load_openvino_model(xml_path: Path, task: str) -> YOLO:
    import openvino as ov

    sys.modules.setdefault("openvino.runtime", ov)
    model = YOLO(str(xml_path.parent), task=task)
    model._model_type = "openvino"
    return model


def resize_long_side(image: np.ndarray, size: int) -> np.ndarray:
    height, width = image.shape[:2]
    if max(height, width) == size:
        return image
    scale = size / max(height, width)
    return cv2.resize(image, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_CUBIC)


def main() -> int:
    args = parse_args()
    if args.output.exists():
        raise FileExistsError(f"Refusing to overwrite output: {args.output}")
    args.output.mkdir(parents=True)
    raw = cv2.imdecode(np.fromfile(str(args.image), dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if raw is None:
        raise RuntimeError(f"Unreadable image: {args.image}")

    seg_model = load_openvino_model(args.seg_model, "segment")
    cls_model = load_openvino_model(args.cls_model, "classify")
    stage1 = infer_single_image(
        seg_model,
        raw,
        crop_size=640,
        overlap=0.2,
        conf_thresh=0.01,
        iou_thresh=0.5,
        padding=32,
        resize_size=2048,
        device="GPU.0",
        use_morphology=True,
        dilate_kernel=3,
        erode_kernel=3,
    )
    crop_source = resize_long_side(raw, 2048)
    names = cls_model.names
    ok_index = next(index for index, name in names.items() if name == "OK")
    overlay = crop_source.copy()
    results = []
    for ordinal, (box, score, class_id) in enumerate(zip(stage1["boxes"], stage1["scores"], stage1["classes"]), start=1):
        x1, y1, x2, y2 = [float(value) for value in box]
        crop, crop_size = _crop_defect_for_classifier(crop_source, {"x1": x1, "y1": y1, "x2": x2, "y2": y2})
        prediction = cls_model.predict(crop, imgsz=224, device="intel:CPU", verbose=False)[0]
        probabilities = prediction.probs.data.detach().float().cpu().numpy()
        top1 = int(np.argmax(probabilities))
        cls_name = str(names[top1])
        ok_probability = float(probabilities[ok_index])
        stage1_name = STAGE1_NAMES[int(class_id)]
        filtered = cls_name == "OK" and ok_probability >= args.ok_threshold
        final_name = "OK_FILTERED" if filtered else (cls_name if cls_name != "OK" else stage1_name)
        item = {
            "candidate": ordinal,
            "box": [round(value, 2) for value in (x1, y1, x2, y2)],
            "stage1": stage1_name,
            "stage1_confidence": round(float(score), 6),
            "classifier": cls_name,
            "classifier_confidence": round(float(probabilities[top1]), 6),
            "ok_probability": round(ok_probability, 6),
            "final": final_name,
            "filtered": filtered,
            "crop_size": int(crop_size),
        }
        results.append(item)
        crop_name = f"p{ordinal:02d}__s1-{stage1_name}-{float(score):.3f}__cls-{cls_name}-{float(probabilities[top1]):.3f}__pok-{ok_probability:.3f}.png"
        cv2.imencode(".png", crop)[1].tofile(str(args.output / crop_name))
        if not filtered:
            cv2.rectangle(overlay, (int(x1), int(y1)), (int(x2), int(y2)), (0, 0, 255), 2)
            cv2.putText(overlay, f"{final_name} {float(score):.2f}", (int(x1), max(18, int(y1) - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 1)

    cv2.imencode(".jpg", overlay, [cv2.IMWRITE_JPEG_QUALITY, 90])[1].tofile(str(args.output / "final_overlay.jpg"))
    summary = {
        "image": str(args.image),
        "config": {"resize": 2048, "crop_size": 640, "overlap": 0.2, "seg_conf": 0.01, "iou": 0.5, "padding": 32, "ok_threshold": args.ok_threshold},
        "stage1_candidates": len(results),
        "final_ng_candidates": sum(not item["filtered"] for item in results),
        "candidates": results,
    }
    (args.output / "result.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
