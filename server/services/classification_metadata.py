# -*- coding: utf-8 -*-
"""分类模型的显示类别名维护。"""

import os
from pathlib import Path


def write_classification_checkpoint_names(weights_paths, class_names: list[str]) -> None:
    """原子更新 Ultralytics 分类权重的 ``model.names``。

    分类训练集使用 ``0000/0001/...`` 目录来固定 ImageFolder label；训练完成
    后将权重中的名称恢复为项目的显示名，供后续继承训练、推理和模型导出使用。
    """
    import torch

    names = {index: str(name) for index, name in enumerate(class_names)}
    handled = set()
    for raw_path in weights_paths:
        if not raw_path:
            continue
        path = Path(raw_path)
        if path in handled or not path.exists():
            continue
        handled.add(path)

        checkpoint = torch.load(str(path), map_location="cpu", weights_only=False)
        if not isinstance(checkpoint, dict):
            raise RuntimeError(f"无法识别分类权重格式：{path}")
        changed = False
        for key in ("model", "ema"):
            model = checkpoint.get(key)
            if model is not None:
                model.names = names.copy()
                changed = True
        if not changed:
            raise RuntimeError(f"分类权重中没有可更新的 model/ema：{path}")

        train_args = checkpoint.get("train_args")
        if isinstance(train_args, dict):
            train_args["class_names"] = list(names.values())
        checkpoint["display_class_names"] = list(names.values())

        temporary = path.with_name(f"{path.name}.names-tmp")
        try:
            torch.save(checkpoint, str(temporary))
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink(missing_ok=True)


def write_openvino_metadata_names(export_path: str, class_names: list[str]) -> None:
    """用 UTF-8 原始类别名更新 OpenVINO metadata.yaml 的 names 段。

    不改 XML/BIN，只改部署端展示与类别解析用的元数据。部署软件的 YAML
    读取器不接受引号或 ``\\uXXXX``，因此明确写成 ``0: 隐裂`` 的形式。
    """
    metadata_path = Path(export_path) / "metadata.yaml"
    if not metadata_path.exists():
        raise RuntimeError(f"OpenVINO 导出缺少 metadata.yaml：{metadata_path}")

    lines = metadata_path.read_text(encoding="utf-8").splitlines()
    start = next((index for index, line in enumerate(lines) if line == "names:"), None)
    if start is None:
        raise RuntimeError(f"OpenVINO metadata.yaml 未找到 names 段：{metadata_path}")

    end = start + 1
    while end < len(lines) and (lines[end].startswith(" ") or not lines[end].strip()):
        end += 1
    name_lines = ["names:"] + [f"  {index}: {name}" for index, name in enumerate(class_names)]
    metadata_path.write_text(
        "\n".join(lines[:start] + name_lines + lines[end:]) + "\n",
        encoding="utf-8",
        newline="\n",
    )
