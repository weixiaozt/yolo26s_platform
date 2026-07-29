"""Run the task68 segmentation + task73 classification cascade on reviewed images.

This utility deliberately reuses the platform's production sliding-window and
classifier-crop functions.  It records every first-stage candidate, evaluates
multiple OK-rejection thresholds, and keeps image-level metrics because the
reviewed folder dataset has class folders but no instance annotations.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("YOLO_AUTOINSTALL", "False")

from core.inference import infer_single_image  # noqa: E402
from server.routers.inference import _crop_defect_for_classifier  # noqa: E402
from ultralytics import YOLO  # noqa: E402


IMAGE_EXTENSIONS = {".bmp", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}
CLASSIFIER_TO_CHINESE = {
    "Crack": "隐裂",
    "EdgeChip": "崩边",
    "Notch": "缺口",
    "OK": "OK",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate the OpenVINO cascade on reviewed images.")
    parser.add_argument("--input", required=True, type=Path, help="Class-folder test root.")
    parser.add_argument("--seg-xml", required=True, type=Path)
    parser.add_argument("--cls-xml", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--seg-device", default="GPU.0")
    parser.add_argument("--cls-device", default="CPU")
    parser.add_argument("--resize", type=int, default=2048)
    parser.add_argument("--crop-size", type=int, default=640)
    parser.add_argument("--overlap", type=float, default=0.2)
    parser.add_argument("--conf", type=float, default=0.01)
    parser.add_argument("--iou", type=float, default=0.5)
    parser.add_argument("--padding", type=int, default=32)
    parser.add_argument("--ok-thresholds", default="0.5,0.7,0.8,0.9")
    return parser.parse_args()


def image_files(root: Path) -> list[tuple[Path, str]]:
    result: list[tuple[Path, str]] = []
    for class_dir in sorted(root.iterdir()):
        if not class_dir.is_dir():
            continue
        for path in sorted(class_dir.rglob("*")):
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
                result.append((path, class_dir.name))
    return result


def resize_for_crop(image: np.ndarray, size: int) -> np.ndarray:
    height, width = image.shape[:2]
    long_side = max(height, width)
    if long_side == size:
        return image
    scale = size / long_side
    return cv2.resize(image, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_CUBIC)


def class_name(names, index: int) -> str:
    if isinstance(names, dict):
        return str(names[index])
    return str(names[index])


def load_openvino_model(model_xml: Path, task: str):
    """Load by model directory while explicitly retaining the model task.

    The OpenVINO directory name alone is insufficient after models are copied
    for precision/version tracking; without ``task`` Ultralytics assumes
    detection and can decode segmentation tensors as unrelated COCO classes.
    """
    try:
        import openvino as ov

        sys.modules.setdefault("openvino.runtime", ov)
    except ImportError:
        pass
    model = YOLO(str(model_xml.parent), task=task)
    model._model_type = "openvino"
    return model


def draw_final_overlay(image: np.ndarray, candidates: list[dict], ok_threshold: float) -> np.ndarray:
    if image.ndim == 2:
        out = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    else:
        out = image.copy()
    for item in candidates:
        keep = item["classifier_name"] != "OK" or item["ok_probability"] < ok_threshold
        if not keep:
            continue
        x1, y1, x2, y2 = (int(round(v)) for v in item["box"])
        shown_name = item["classifier_chinese"] if item["classifier_name"] != "OK" else item["stage1_name"]
        cv2.rectangle(out, (x1, y1), (x2, y2), (0, 0, 255), 2)
        cv2.putText(
            out,
            f"{shown_name} {item['stage1_confidence']:.2f}",
            (x1, max(18, y1 - 6)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (0, 0, 255),
            1,
            cv2.LINE_AA,
        )
    return out


def main() -> int:
    args = parse_args()
    thresholds = [float(value) for value in args.ok_thresholds.split(",")]
    if not thresholds or any(not 0.0 <= value <= 1.0 for value in thresholds):
        raise ValueError("--ok-thresholds must be comma-separated values in [0, 1]")

    files = image_files(args.input)
    if not files:
        raise RuntimeError(f"No images found under {args.input}")

    args.output.mkdir(parents=True, exist_ok=True)
    overlay_dir = args.output / "overlays_t080"
    overlay_dir.mkdir(exist_ok=True)
    image_csv = args.output / "per_image.csv"
    candidate_csv = args.output / "per_candidate.csv"
    report_json = args.output / "cascade_report.json"

    print(f"[start] images={len(files)} input={args.input}", flush=True)
    print(f"[config] resize={args.resize} crop={args.crop_size} overlap={args.overlap} conf={args.conf}", flush=True)
    print(f"[config] seg={args.seg_xml} ({args.seg_device})", flush=True)
    print(f"[config] cls={args.cls_xml} ({args.cls_device})", flush=True)

    seg_model = load_openvino_model(args.seg_xml, task="segment")
    cls_model = load_openvino_model(args.cls_xml, task="classify")
    classifier_names = getattr(cls_model, "names", {})
    ok_index = next((idx for idx in classifier_names if class_name(classifier_names, idx) == "OK"), None)
    if ok_index is None:
        raise RuntimeError(f"Classifier has no OK class: {classifier_names}")

    per_image: list[dict] = []
    per_candidate: list[dict] = []
    total_started = time.perf_counter()

    for ordinal, (path, ground_truth) in enumerate(files, start=1):
        image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if image is None:
            print(f"[warn] unreadable {path}", flush=True)
            continue

        started = time.perf_counter()
        stage1 = infer_single_image(
            seg_model,
            image,
            crop_size=args.crop_size,
            overlap=args.overlap,
            conf_thresh=args.conf,
            iou_thresh=args.iou,
            padding=args.padding,
            resize_size=args.resize,
            device=args.seg_device,
            use_morphology=True,
            dilate_kernel=3,
            erode_kernel=3,
        )
        stage1_seconds = time.perf_counter() - started

        crop_source = resize_for_crop(image, args.resize)
        candidates: list[dict] = []
        crops: list[np.ndarray] = []
        for candidate_index, (box, confidence, class_id) in enumerate(
            zip(stage1["boxes"], stage1["scores"], stage1["classes"]), start=1
        ):
            box_list = [float(value) for value in box]
            crop, crop_size = _crop_defect_for_classifier(crop_source, {"x1": box_list[0], "y1": box_list[1], "x2": box_list[2], "y2": box_list[3]})
            candidates.append(
                {
                    "candidate_index": candidate_index,
                    "box": box_list,
                    "stage1_class_id": int(class_id),
                    "stage1_name": class_name(getattr(seg_model, "names", {}), int(class_id)),
                    "stage1_confidence": float(confidence),
                    "crop_size": int(crop_size),
                }
            )
            crops.append(crop)

        classifier_seconds = 0.0
        if crops:
            classifier_started = time.perf_counter()
            # The exported classifier uses a static [1, 3, 224, 224] input.
            # Submit each crop separately so a multi-candidate image never
            # becomes an incompatible batch.  Production batching can be added
            # later by exporting a dynamic/batched classifier explicitly.
            predictions = []
            for crop in crops:
                single = cls_model.predict(
                    crop,
                    imgsz=224,
                    device="intel:CPU" if args.cls_device.upper() == "CPU" else "intel:GPU.0",
                    verbose=False,
                    stream=False,
                )
                predictions.append(single[0])
            classifier_seconds = time.perf_counter() - classifier_started
            if len(predictions) != len(candidates):
                raise RuntimeError(f"Classifier output count mismatch for {path.name}")
            for candidate, prediction in zip(candidates, predictions):
                probabilities = prediction.probs.data.detach().float().cpu().numpy()
                top1 = int(np.argmax(probabilities))
                candidate["classifier_name"] = class_name(classifier_names, top1)
                candidate["classifier_chinese"] = CLASSIFIER_TO_CHINESE.get(candidate["classifier_name"], candidate["classifier_name"])
                candidate["classifier_confidence"] = float(probabilities[top1])
                candidate["ok_probability"] = float(probabilities[ok_index])

        for candidate in candidates:
            per_candidate.append(
                {
                    "image": str(path.relative_to(args.input)).replace("\\", "/"),
                    "ground_truth": ground_truth,
                    **{key: candidate[key] for key in (
                        "candidate_index", "stage1_class_id", "stage1_name", "stage1_confidence",
                        "crop_size", "classifier_name", "classifier_chinese", "classifier_confidence", "ok_probability",
                    )},
                    "box": json.dumps([round(value, 2) for value in candidate["box"]]),
                }
            )

        image_record = {
            "image": str(path.relative_to(args.input)).replace("\\", "/"),
            "ground_truth": ground_truth,
            "stage1_candidates": len(candidates),
            "stage1_seconds": stage1_seconds,
            "classifier_seconds": classifier_seconds,
            "total_seconds": time.perf_counter() - started,
            "max_stage1_confidence": max((item["stage1_confidence"] for item in candidates), default=0.0),
        }
        for threshold in thresholds:
            key = f"t{int(round(threshold * 100)):03d}"
            kept = [
                item for item in candidates
                if item["classifier_name"] != "OK" or item["ok_probability"] < threshold
            ]
            output_classes = [
                item["classifier_chinese"] if item["classifier_name"] != "OK" else item["stage1_name"]
                for item in kept
            ]
            image_record[f"{key}_kept"] = len(kept)
            image_record[f"{key}_classes"] = ";".join(output_classes)

        per_image.append(image_record)
        overlay = draw_final_overlay(crop_source, candidates, 0.8)
        cv2.imwrite(str(overlay_dir / f"{path.stem}.jpg"), overlay, [cv2.IMWRITE_JPEG_QUALITY, 90])
        print(
            f"[progress] {ordinal}/{len(files)} {image_record['image']} "
            f"cand={len(candidates)} stage1={stage1_seconds:.3f}s cls={classifier_seconds:.3f}s",
            flush=True,
        )

    summaries = {}
    for threshold in thresholds:
        key = f"t{int(round(threshold * 100)):03d}"
        summary = {
            "total_images": len(per_image),
            "ok_total": 0,
            "ok_false_positive": 0,
            "ng_total": 0,
            "ng_detected": 0,
            "strict_class_correct": 0,
            "soft_class_correct": 0,
            "candidate_before": sum(row["stage1_candidates"] for row in per_image),
            "candidate_after": sum(row[f"{key}_kept"] for row in per_image),
        }
        class_metrics = defaultdict(lambda: {"total": 0, "detected": 0, "strict_correct": 0, "soft_correct": 0})
        for row in per_image:
            ground_truth = row["ground_truth"]
            predicted_classes = [item for item in row[f"{key}_classes"].split(";") if item]
            if ground_truth == "OK":
                summary["ok_total"] += 1
                if predicted_classes:
                    summary["ok_false_positive"] += 1
                else:
                    summary["strict_class_correct"] += 1
                    summary["soft_class_correct"] += 1
                continue
            summary["ng_total"] += 1
            class_metrics[ground_truth]["total"] += 1
            if predicted_classes:
                summary["ng_detected"] += 1
                class_metrics[ground_truth]["detected"] += 1
            if ground_truth in predicted_classes:
                summary["strict_class_correct"] += 1
                class_metrics[ground_truth]["strict_correct"] += 1
            soft_match = ground_truth in predicted_classes or (
                ground_truth in {"隐裂", "缺口"} and any(item in {"隐裂", "缺口"} for item in predicted_classes)
            )
            if soft_match:
                summary["soft_class_correct"] += 1
                class_metrics[ground_truth]["soft_correct"] += 1
        summary["ok_false_positive_rate"] = summary["ok_false_positive"] / summary["ok_total"] if summary["ok_total"] else 0.0
        summary["ng_recall"] = summary["ng_detected"] / summary["ng_total"] if summary["ng_total"] else 0.0
        summary["strict_image_accuracy"] = summary["strict_class_correct"] / summary["total_images"] if summary["total_images"] else 0.0
        summary["soft_image_accuracy"] = summary["soft_class_correct"] / summary["total_images"] if summary["total_images"] else 0.0
        summary["per_class"] = dict(class_metrics)
        summaries[key] = summary

    timing = {
        "total_seconds": time.perf_counter() - total_started,
        "images": len(per_image),
        "avg_stage1_seconds": sum(row["stage1_seconds"] for row in per_image) / len(per_image),
        "avg_classifier_seconds": sum(row["classifier_seconds"] for row in per_image) / len(per_image),
        "avg_total_seconds": sum(row["total_seconds"] for row in per_image) / len(per_image),
        "p95_total_seconds": float(np.percentile([row["total_seconds"] for row in per_image], 95)),
    }
    report = {
        "models": {"seg": str(args.seg_xml), "cls": str(args.cls_xml)},
        "devices": {"seg": args.seg_device, "cls": args.cls_device},
        "config": {
            "resize": args.resize, "crop_size": args.crop_size, "overlap": args.overlap,
            "conf": args.conf, "iou": args.iou, "padding": args.padding, "thresholds": thresholds,
        },
        "timing": timing,
        "threshold_summaries": summaries,
        "files": {"per_image": str(image_csv), "per_candidate": str(candidate_csv), "overlays": str(overlay_dir)},
    }

    image_fields = sorted({field for row in per_image for field in row})
    with image_csv.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=image_fields)
        writer.writeheader()
        writer.writerows(per_image)
    candidate_fields = [
        "image", "ground_truth", "candidate_index", "stage1_class_id", "stage1_name", "stage1_confidence",
        "crop_size", "classifier_name", "classifier_chinese", "classifier_confidence", "ok_probability", "box",
    ]
    with candidate_csv.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=candidate_fields)
        writer.writeheader()
        writer.writerows(per_candidate)
    report_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[result] " + json.dumps({"timing": timing, "thresholds": summaries}, ensure_ascii=False), flush=True)
    print(f"[done] report={report_json}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
