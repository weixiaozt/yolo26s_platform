"""Replace YAML Unicode escapes with literal UTF-8 class names for legacy consumers."""

from pathlib import Path
import re


TARGET = Path(
    r"D:\yolo26s_platform\storage\deployment_packages"
    r"\task73_stage2_classifier_openvino_fp16_chinese_plain_20260729"
    r"\best_openvino_model\metadata.yaml"
)


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")
    mapping = {
        "Crack": "".join(map(chr, (0x9690, 0x88C2))),
        "EdgeChip": "".join(map(chr, (0x5D29, 0x8FB9))),
        "Notch": "".join(map(chr, (0x7F3A, 0x53E3))),
    }
    for source, replacement in mapping.items():
        text = re.sub(
            rf"(?m)^(\s*\d+:\s*){source}$",
            lambda match: f"{match.group(1)}{replacement}",
            text,
        )
    TARGET.write_text(text, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
