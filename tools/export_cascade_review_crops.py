"""Materialize the exact second-stage crops from a saved cascade evaluation."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import cv2
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from server.routers.inference import _crop_defect_for_classifier  # noqa: E402


STAGE1_NAMES = {0: "Crack", 1: "EdgeChip", 2: "Notch"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path, help="Original class-folder images.")
    parser.add_argument("--evaluation", required=True, type=Path, help="Cascade evaluation output directory.")
    parser.add_argument("--threshold", type=float, default=0.7, help="OK suppression threshold.")
    parser.add_argument("--resize", type=int, default=2048, help="Must match cascade evaluation resize.")
    return parser.parse_args()


def resize_for_crop(image, size: int):
    height, width = image.shape[:2]
    scale = size / max(height, width)
    if scale == 1:
        return image
    return cv2.resize(image, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_CUBIC)


def decision(row: dict[str, str], threshold: float) -> tuple[str, str]:
    stage1 = STAGE1_NAMES[int(row["stage1_class_id"])]
    classifier = row["classifier_name"]
    ok_probability = float(row["ok_probability"])
    if classifier == "OK" and ok_probability >= threshold:
        return "filtered_ok", "OK"
    if classifier == "OK":
        return f"kept_{stage1}_low_ok", stage1
    return f"kept_{classifier}", classifier


def write_crop(crop, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(destination), crop, [cv2.IMWRITE_PNG_COMPRESSION, 2]):
        raise RuntimeError(f"Failed writing {destination}")


def main() -> int:
    args = parse_args()
    csv_path = args.evaluation / "per_candidate.csv"
    if not csv_path.is_file():
        raise FileNotFoundError(csv_path)
    output = args.evaluation / f"review_crops_t{int(args.threshold * 100):03d}_v3"
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite existing review crops: {output}")
    output.mkdir(parents=True)

    with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))

    image_cache: dict[str, object] = {}
    manifest: list[dict[str, str]] = []
    for ordinal, row in enumerate(rows, start=1):
        relative = row["image"]
        source = args.input / Path(relative)
        if relative not in image_cache:
            # OpenCV's Windows narrow-path reader cannot open the Chinese test-folder name.
            original = cv2.imdecode(np.fromfile(str(source), dtype=np.uint8), cv2.IMREAD_UNCHANGED)
            if original is None:
                raise RuntimeError(f"Unreadable source image: {source}")
            image_cache[relative] = resize_for_crop(original, args.resize)
        box = json.loads(row["box"])
        crop, crop_size = _crop_defect_for_classifier(
            image_cache[relative],
            {"x1": box[0], "y1": box[1], "x2": box[2], "y2": box[3]},
        )
        folder, final_class = decision(row, args.threshold)
        stage1 = STAGE1_NAMES[int(row["stage1_class_id"])]
        stem = Path(relative).stem
        filename = (
            f"{stem}__p{int(row['candidate_index']):03d}"
            f"__s1-{stage1}-{float(row['stage1_confidence']):.3f}"
            f"__cls-{row['classifier_name']}-{float(row['classifier_confidence']):.3f}"
            f"__pok-{float(row['ok_probability']):.3f}.png"
        )
        relative_output = Path("all") / folder / filename
        write_crop(crop, output / relative_output)

        is_reclassified = row["classifier_name"] != "OK" and row["classifier_name"] != stage1
        if is_reclassified:
            write_crop(crop, output / "focus" / "reclassified" / filename)
        if folder == "filtered_ok" and row["ground_truth"] == "OK":
            write_crop(crop, output / "focus" / "corrected_known_ok" / filename)
        if folder == "filtered_ok" and row["ground_truth"] != "OK":
            write_crop(crop, output / "focus" / "filtered_from_ng_images" / filename)

        manifest.append(
            {
                "crop": str(relative_output).replace("\\", "/"),
                "source_image": relative,
                "source_folder": row["ground_truth"],
                "candidate_index": row["candidate_index"],
                "stage1_class": stage1,
                "stage1_confidence": row["stage1_confidence"],
                "classifier_class": row["classifier_name"],
                "classifier_confidence": row["classifier_confidence"],
                "ok_probability": row["ok_probability"],
                "final_decision": folder,
                "final_class": final_class,
                "crop_size": str(crop_size),
                "box": row["box"],
            }
        )
        if ordinal % 50 == 0 or ordinal == len(rows):
            print(f"[progress] {ordinal}/{len(rows)}", flush=True)

    fieldnames = list(manifest[0])
    with (output / "manifest.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(manifest)
    print(f"[done] crops={len(manifest)} output={output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
