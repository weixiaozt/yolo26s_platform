"""Export isolated FP32 OpenVINO copies without replacing deployment exports."""

from pathlib import Path

from ultralytics import YOLO


ROOT = Path(r"D:\yolo26s_platform\storage\runs")
SEG = ROOT / "task_68" / "fp32_comparison_export" / "best.pt"
CLS = (
    ROOT
    / "cascade_classifier_20260729"
    / "closedset_4class_nano_v2_20260729"
    / "nano_4class"
    / "fp32_comparison_export"
    / "best.pt"
)


def main() -> None:
    for source, task, imgsz in ((SEG, "segment", 640), (CLS, "classify", 224)):
        if not source.is_file():
            raise FileNotFoundError(source)
        print(f"Exporting FP32 {task}: {source}", flush=True)
        output = YOLO(str(source), task=task).export(
            format="openvino", imgsz=imgsz, half=False, device="cpu"
        )
        print(f"Done: {output}", flush=True)


if __name__ == "__main__":
    main()
