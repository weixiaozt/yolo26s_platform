# -*- coding: utf-8 -*-
"""
EasyLabel VOC XML → YOLO Detection 格式转换 + 训练脚本
=====================================================
功能：
  1. 解析 EasyLabel 导出的 Pascal VOC XML 标注
  2. 转换为 YOLO txt 格式 (class_id cx cy w h，归一化)
  3. 自动划分 train / val
  4. 生成 dataset.yaml
  5. 可选：直接启动训练

用法：
  python tools/convert_voc_to_yolo_det.py \
      --src "D:\EasyLabel_x64\EasyLabelData\Style\ObjectDetect\光伏面板检测\Data" \
      --out "D:\yolo26s_platform\runs\det_panel" \
      --train-ratio 0.85 \
      --train  # 加此参数自动开始训练
"""

import argparse
import random
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path


def parse_voc_xml(xml_path: Path) -> dict:
    """解析一个 VOC XML 文件，返回图像信息和所有 bndbox"""
    tree = ET.parse(str(xml_path))
    root = tree.getroot()

    size = root.find("size")
    w = int(size.find("width").text)
    h = int(size.find("height").text)
    filename = root.find("filename").text

    objects = []
    for obj in root.findall("object"):
        name = obj.find("name").text
        bndbox = obj.find("bndbox")
        xmin = float(bndbox.find("xmin").text)
        ymin = float(bndbox.find("ymin").text)
        xmax = float(bndbox.find("xmax").text)
        ymax = float(bndbox.find("ymax").text)
        objects.append({
            "name": name,
            "xmin": xmin, "ymin": ymin,
            "xmax": xmax, "ymax": ymax,
        })

    return {"filename": filename, "width": w, "height": h, "objects": objects}


def voc_to_yolo_line(obj: dict, img_w: int, img_h: int, class_map: dict) -> str | None:
    """将一个 VOC bbox 转为 YOLO 格式行: class_id cx cy w h (归一化)"""
    name = obj["name"]
    if name not in class_map:
        return None

    class_id = class_map[name]

    # 限制坐标范围
    xmin = max(0, obj["xmin"])
    ymin = max(0, obj["ymin"])
    xmax = min(img_w, obj["xmax"])
    ymax = min(img_h, obj["ymax"])

    cx = (xmin + xmax) / 2.0 / img_w
    cy = (ymin + ymax) / 2.0 / img_h
    bw = (xmax - xmin) / img_w
    bh = (ymax - ymin) / img_h

    # 跳过无效框
    if bw <= 0 or bh <= 0:
        return None

    return f"{class_id} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}"


def convert_dataset(src_dir: Path, out_dir: Path, train_ratio: float = 0.85, seed: int = 42):
    """
    主转换流程：
    1. 扫描所有 XML，提取类别
    2. 转换标注
    3. 复制图片
    4. 划分 train/val
    5. 生成 dataset.yaml
    """
    # 扫描所有 XML
    xml_files = sorted(src_dir.glob("*.xml"))
    if not xml_files:
        print(f"[错误] {src_dir} 下没有找到 XML 文件")
        return None

    print(f"找到 {len(xml_files)} 个 XML 标注文件")

    # 第一遍扫描：提取所有类别名
    all_classes = set()
    parsed_data = []
    for xf in xml_files:
        data = parse_voc_xml(xf)
        parsed_data.append((xf, data))
        for obj in data["objects"]:
            all_classes.add(obj["name"])

    class_names = sorted(all_classes)
    class_map = {name: idx for idx, name in enumerate(class_names)}
    print(f"类别: {class_names}")
    print(f"类别映射: {class_map}")

    # 寻找匹配的图像文件
    img_exts = [".bmp", ".png", ".jpg", ".jpeg", ".tif", ".tiff"]
    valid_pairs = []  # (xml_path, img_path, parsed_data)

    for xf, data in parsed_data:
        stem = xf.stem
        img_path = None
        for ext in img_exts:
            candidate = src_dir / f"{stem}{ext}"
            if candidate.exists():
                img_path = candidate
                break
        if img_path is None:
            print(f"  [跳过] {stem}: 找不到对应图片")
            continue
        valid_pairs.append((xf, img_path, data))

    print(f"有效图片-标注对: {len(valid_pairs)}")

    if not valid_pairs:
        print("[错误] 没有有效的图片-标注对")
        return None

    # 划分 train / val
    random.seed(seed)
    indices = list(range(len(valid_pairs)))
    random.shuffle(indices)
    split_idx = int(len(indices) * train_ratio)
    train_indices = set(indices[:split_idx])
    val_indices = set(indices[split_idx:])

    print(f"训练集: {len(train_indices)} 张, 验证集: {len(val_indices)} 张")

    # 创建输出目录
    for split in ("train", "val"):
        (out_dir / "images" / split).mkdir(parents=True, exist_ok=True)
        (out_dir / "labels" / split).mkdir(parents=True, exist_ok=True)

    # 转换并复制
    total_boxes = 0
    for i, (xf, img_path, data) in enumerate(valid_pairs):
        split = "train" if i in train_indices else "val"

        # 转换为 YOLO txt
        lines = []
        for obj in data["objects"]:
            line = voc_to_yolo_line(obj, data["width"], data["height"], class_map)
            if line:
                lines.append(line)
                total_boxes += 1

        # 写入 label txt（用与图片同名的 .txt）
        # 图片统一转为 .jpg 后缀（YOLO 默认支持）
        out_img_name = f"{xf.stem}.bmp"
        out_txt_name = f"{xf.stem}.txt"

        label_path = out_dir / "labels" / split / out_txt_name
        label_path.write_text("\n".join(lines), encoding="utf-8")

        # 复制图片
        dst_img = out_dir / "images" / split / out_img_name
        shutil.copy2(str(img_path), str(dst_img))

    print(f"总共转换 {total_boxes} 个 bbox")

    # 生成 dataset.yaml
    yaml_path = out_dir / "dataset.yaml"
    yaml_content = f"""# YOLO Detection Dataset - Auto Generated
path: {out_dir.as_posix()}
train: images/train
val: images/val

nc: {len(class_names)}
names: {class_names}
"""
    yaml_path.write_text(yaml_content, encoding="utf-8")
    print(f"\ndataset.yaml 已生成: {yaml_path}")

    return {
        "dataset_yaml": str(yaml_path),
        "class_names": class_names,
        "num_train": len(train_indices),
        "num_val": len(val_indices),
        "total_boxes": total_boxes,
    }


def run_training(dataset_yaml: str, output_dir: str, **kwargs):
    """使用 Ultralytics YOLO 进行目标检测训练"""
    from ultralytics import YOLO

    model_name = kwargs.get("model_name", "yolo11s.pt")
    imgsz = kwargs.get("imgsz", 640)
    epochs = kwargs.get("epochs", 200)
    batch_size = kwargs.get("batch_size", 16)
    patience = kwargs.get("patience", 50)
    device = kwargs.get("device", "0")

    print(f"\n{'='*60}")
    print(f"开始目标检测训练")
    print(f"  模型: {model_name}")
    print(f"  数据集: {dataset_yaml}")
    print(f"  图像大小: {imgsz}")
    print(f"  Epochs: {epochs}")
    print(f"  Batch: {batch_size}")
    print(f"  Patience: {patience}")
    print(f"  Device: {device}")
    print(f"{'='*60}\n")

    model = YOLO(model_name)
    results = model.train(
        data=dataset_yaml,
        imgsz=imgsz,
        epochs=epochs,
        batch=batch_size,
        patience=patience,
        device=device,
        project=output_dir,
        name="detect",
        exist_ok=True,
        # 数据增强
        hsv_h=0.015,
        hsv_s=0.7,
        hsv_v=0.4,
        degrees=10.0,
        translate=0.1,
        scale=0.5,
        shear=5.0,
        flipud=0.5,
        fliplr=0.5,
        mosaic=0.5,
        mixup=0.1,
        copy_paste=0.0,
    )

    # 输出最终结果
    print(f"\n{'='*60}")
    print(f"训练完成!")
    best_pt = Path(output_dir) / "detect" / "weights" / "best.pt"
    last_pt = Path(output_dir) / "detect" / "weights" / "last.pt"
    print(f"  Best 模型: {best_pt}")
    print(f"  Last 模型: {last_pt}")
    print(f"{'='*60}")

    return {"best_pt": str(best_pt), "last_pt": str(last_pt)}


def main():
    parser = argparse.ArgumentParser(description="EasyLabel VOC XML → YOLO Detection 转换+训练")
    parser.add_argument("--src", required=True, help="EasyLabel 数据目录（含 .bmp + .xml）")
    parser.add_argument("--out", required=True, help="输出 YOLO 数据集目录")
    parser.add_argument("--train-ratio", type=float, default=0.85, help="训练集比例 (默认 0.85)")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")

    # 训练参数
    parser.add_argument("--train", action="store_true", help="转换后自动开始训练")
    parser.add_argument("--model", default="yolo11s.pt", help="模型名称 (默认 yolo11s.pt)")
    parser.add_argument("--imgsz", type=int, default=640, help="训练图像大小 (默认 640)")
    parser.add_argument("--epochs", type=int, default=200, help="训练轮数 (默认 200)")
    parser.add_argument("--batch", type=int, default=16, help="Batch size (默认 16)")
    parser.add_argument("--patience", type=int, default=50, help="早停耐心值 (默认 50)")
    parser.add_argument("--device", default="0", help="GPU 设备 (默认 0)")

    args = parser.parse_args()

    src_dir = Path(args.src)
    out_dir = Path(args.out)

    if not src_dir.exists():
        print(f"[错误] 源目录不存在: {src_dir}")
        return

    print(f"源目录: {src_dir}")
    print(f"输出目录: {out_dir}")
    print()

    # 转换数据集
    result = convert_dataset(src_dir, out_dir, args.train_ratio, args.seed)
    if result is None:
        return

    print(f"\n转换完成!")
    print(f"  训练集: {result['num_train']} 张")
    print(f"  验证集: {result['num_val']} 张")
    print(f"  总 bbox: {result['total_boxes']}")
    print(f"  dataset.yaml: {result['dataset_yaml']}")

    # 可选：开始训练
    if args.train:
        run_training(
            dataset_yaml=result["dataset_yaml"],
            output_dir=str(out_dir),
            model_name=args.model,
            imgsz=args.imgsz,
            epochs=args.epochs,
            batch_size=args.batch,
            patience=args.patience,
            device=args.device,
        )
    else:
        print(f"\n如需训练，请运行:")
        print(f'  python tools/convert_voc_to_yolo_det.py --src "{src_dir}" --out "{out_dir}" --train')
        print(f"\n或手动用 Ultralytics CLI:")
        print(f'  yolo detect train data="{result["dataset_yaml"]}" model=yolo11s.pt imgsz=640 epochs=200 batch=16 device=0')


if __name__ == "__main__":
    main()
