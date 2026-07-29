"""Evaluate a YOLO classification model against an ImageFolder dataset.

The input paths are submitted to Ultralytics in bounded chunks.  Passing a
large list of paths in one predict() call can make the loader decode the whole
closed set at once and exhaust Windows RAM/pagefile.
"""

from __future__ import annotations

import argparse
import csv
import gc
import json
import time
from collections import Counter, defaultdict
from pathlib import Path

import torch
from ultralytics import YOLO


IMAGE_EXTENSIONS = {".bmp", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate exact closed-set classification accuracy.")
    parser.add_argument("--model", required=True, type=Path, help="Path to best.pt.")
    parser.add_argument("--dataset", required=True, type=Path, help="ImageFolder split to evaluate.")
    parser.add_argument("--output-dir", type=Path, help="Report directory (defaults beside the run).")
    parser.add_argument("--imgsz", type=int, default=224)
    parser.add_argument("--batch", type=int, default=128)
    parser.add_argument("--device", default="0")
    parser.add_argument("--threshold", type=float, default=0.995)
    return parser.parse_args()


def collect_items(dataset: Path) -> list[tuple[Path, str]]:
    items: list[tuple[Path, str]] = []
    for class_dir in sorted(dataset.iterdir()):
        if not class_dir.is_dir():
            continue
        for image_path in sorted(class_dir.iterdir()):
            if image_path.is_file() and image_path.suffix.lower() in IMAGE_EXTENSIONS:
                items.append((image_path, class_dir.name))
    return items


def main() -> int:
    args = parse_args()
    model_path = args.model.resolve()
    dataset = args.dataset.resolve()
    output_dir = (args.output_dir or model_path.parent.parent).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    report_path = output_dir / "closedset_eval_report.json"
    errors_path = output_dir / "closedset_eval_errors.csv"
    items = collect_items(dataset)
    if not items:
        raise RuntimeError(f"No classification images found under {dataset}")

    print(f"[eval] model={model_path}", flush=True)
    print(f"[eval] dataset={dataset}", flush=True)
    print(f"[eval] images={len(items)} classes={sorted({label for _, label in items})}", flush=True)

    model = YOLO(str(model_path))
    print(f"[eval] model.names={dict(model.names)}", flush=True)

    correct = 0
    per_class_total: Counter[str] = Counter()
    per_class_correct: Counter[str] = Counter()
    confusion: dict[str, Counter[str]] = defaultdict(Counter)
    errors: list[dict[str, object]] = []
    started = time.perf_counter()

    try:
        for offset in range(0, len(items), args.batch):
            chunk = items[offset : offset + args.batch]
            paths = [str(path) for path, _ in chunk]
            predictions = model.predict(
                source=paths,
                imgsz=args.imgsz,
                batch=min(args.batch, len(chunk)),
                device=args.device,
                verbose=False,
                stream=False,
            )
            if len(predictions) != len(chunk):
                raise RuntimeError(
                    f"Prediction count mismatch at offset {offset}: "
                    f"{len(predictions)} != {len(chunk)}"
                )

            for prediction, (image_path, ground_truth) in zip(predictions, chunk):
                probabilities = prediction.probs.data.detach().float().cpu()
                ranking = torch.argsort(probabilities, descending=True)
                predicted_index = int(ranking[0])
                second_index = int(ranking[1]) if len(ranking) > 1 else predicted_index
                predicted_name = str(model.names[predicted_index])
                second_name = str(model.names[second_index])

                per_class_total[ground_truth] += 1
                confusion[ground_truth][predicted_name] += 1
                if predicted_name == ground_truth:
                    correct += 1
                    per_class_correct[ground_truth] += 1
                else:
                    errors.append(
                        {
                            "file": image_path.name,
                            "path": str(image_path),
                            "ground_truth": ground_truth,
                            "predicted": predicted_name,
                            "confidence": round(float(probabilities[predicted_index]), 6),
                            "second": second_name,
                            "second_confidence": round(float(probabilities[second_index]), 6),
                        }
                    )

            completed = offset + len(chunk)
            print(
                f"[eval] {completed}/{len(items)} "
                f"correct={correct} wrong={completed - correct}",
                flush=True,
            )
            del predictions
    finally:
        del model
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            try:
                torch.cuda.ipc_collect()
            except Exception:
                pass

    elapsed = time.perf_counter() - started
    accuracy = correct / len(items)
    per_class = []
    for class_name in sorted(per_class_total):
        total = per_class_total[class_name]
        class_correct = per_class_correct[class_name]
        per_class.append(
            {
                "class": class_name,
                "total": total,
                "correct": class_correct,
                "wrong": total - class_correct,
                "accuracy": class_correct / total,
            }
        )

    report = {
        "model": str(model_path),
        "dataset": str(dataset),
        "total": len(items),
        "correct": correct,
        "wrong": len(items) - correct,
        "accuracy": accuracy,
        "threshold": args.threshold,
        "pass": accuracy >= args.threshold,
        "elapsed_seconds": elapsed,
        "images_per_second": len(items) / elapsed,
        "per_class": per_class,
        "confusion": {label: dict(row) for label, row in confusion.items()},
        "errors": errors,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    with errors_path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "file",
                "path",
                "ground_truth",
                "predicted",
                "confidence",
                "second",
                "second_confidence",
            ],
        )
        writer.writeheader()
        writer.writerows(errors)

    print(
        "[eval] RESULT "
        + json.dumps(
            {
                "total": len(items),
                "correct": correct,
                "wrong": len(items) - correct,
                "accuracy": accuracy,
                "pass": accuracy >= args.threshold,
                "elapsed_seconds": elapsed,
                "images_per_second": len(items) / elapsed,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    print(f"[eval] report={report_path}", flush=True)
    print(f"[eval] errors={errors_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
