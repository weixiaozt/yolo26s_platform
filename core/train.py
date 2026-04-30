# -*- coding: utf-8 -*-
"""
模型训练模块 (train.py)
========================
功能：调用 Ultralytics YOLO26s-seg 进行实例分割训练，
      通过 on_fit_epoch_end 回调实时回传每个 epoch 的训练指标，
      训练完成后自动绘制 Loss 曲线和验证指标曲线。

回调机制说明：
    - Ultralytics 提供 on_fit_epoch_end 回调，在每个 epoch 的训练+验证完成后触发
    - 回调函数接收 trainer 对象，可从中读取：
        trainer.epoch        当前 epoch 编号
        trainer.epochs       总 epoch 数
        trainer.loss_items   各项 loss 值 (Tensor)
        trainer.loss_names   loss 名称列表 ['box_loss', 'seg_loss', 'cls_loss', 'dfl_loss']
        trainer.tloss        总 loss 值 (Tensor)
        trainer.metrics      验证指标字典 (mAP50, mAP50-95, precision, recall 等)
        trainer.best_fitness 最佳 fitness 值
    - 通过 epoch_callback 参数，将这些指标实时传递给 GUI 线程

输入：
    - 数据集路径（包含 dataset.yaml）
    - 训练超参数（epochs, batch_size, imgsz, 增广参数等）
    - epoch_callback: 每个 epoch 结束后的回调函数

输出：
    - 训练权重 best.pt / last.pt
    - 训练曲线图
    - results.csv
"""

import os
import yaml
import matplotlib
matplotlib.use('Agg')  # 非交互式后端，避免 GUI 线程冲突
import matplotlib.pyplot as plt
import pandas as pd
from pathlib import Path
from typing import Optional, Callable, Dict, Any


def generate_dataset_yaml(
    dataset_dir: str,
    output_path: str,
    class_names: list = None
) -> str:
    """
    生成 YOLO 训练所需的 dataset.yaml 文件。

    Args:
        dataset_dir: 数据集根目录（包含 images/{train,val}/ 和 labels/{train,val}/）
        output_path: dataset.yaml 的保存路径
        class_names: 类别名称列表，默认为硅片缺陷类别

    Returns:
        生成的 dataset.yaml 文件路径
    """
    if class_names is None:
        class_names = ['defect_1', 'defect_2', 'defect_3']

    # 使用绝对路径，确保训练时能正确找到数据
    dataset_dir = str(Path(dataset_dir).resolve())

    config = {
        'path': dataset_dir,
        'train': 'images/train',
        'val': 'images/val',
        'nc': len(class_names),
        'names': class_names,
    }

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

    return str(output_path)


def plot_training_curves(results_csv: str, save_dir: str):
    """
    根据训练日志 results.csv 绘制训练曲线图。
    格式与 Ultralytics 官方一致：2x2 布局，Train(蓝实线) vs Val(红虚线)

    Args:
        results_csv: results.csv 文件路径
        save_dir: 图表保存目录
    """
    save_dir = Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)

    # 读取 CSV（Ultralytics 的 CSV 列名前后可能有空格）
    df = pd.read_csv(results_csv)
    df.columns = df.columns.str.strip()

    epochs = df['epoch'] if 'epoch' in df.columns else range(len(df))

    # ---- 图1: Train vs Validation Loss (官方格式 2x2) ----
    fig, axes = plt.subplots(2, 2, figsize=(12, 9))
    fig.suptitle('Train vs Validation Loss', fontsize=16, fontweight='bold')

    loss_pairs = [
        ('train/box_loss', 'val/box_loss', 'Box Loss'),
        ('train/seg_loss', 'val/seg_loss', 'Seg Loss'),
        ('train/cls_loss', 'val/cls_loss', 'Cls Loss'),
        ('train/dfl_loss', 'val/dfl_loss', 'DFL Loss'),
    ]

    for ax, (train_col, val_col, title) in zip(axes.flat, loss_pairs):
        if train_col in df.columns:
            ax.plot(epochs, df[train_col], 'b-', label='Train', linewidth=1.5)
        if val_col in df.columns:
            ax.plot(epochs, df[val_col], 'r--', label='Val', linewidth=1.5)
        ax.set_title(title, fontsize=12)
        ax.set_xlabel('Epoch')
        ax.set_ylabel('Loss')
        ax.legend()
        ax.grid(True, alpha=0.3)

    plt.tight_layout(rect=[0, 0, 1, 0.96])  # 为总标题留出空间
    plt.savefig(str(save_dir / 'loss_curves.png'), dpi=150, bbox_inches='tight')
    plt.close()

    # ---- 图2: 验证指标曲线 (2x2) ----
    fig, axes = plt.subplots(2, 2, figsize=(12, 9))
    fig.suptitle('Validation Metrics', fontsize=16, fontweight='bold')

    metric_cols = [
        ('metrics/precision(B)', 'Precision (Box)'),
        ('metrics/recall(B)', 'Recall (Box)'),
        ('metrics/mAP50(B)', 'mAP@0.5 (Box)'),
        ('metrics/mAP50-95(B)', 'mAP@0.5:0.95 (Box)'),
    ]

    for ax, (col, title) in zip(axes.flat, metric_cols):
        if col in df.columns:
            ax.plot(epochs, df[col], 'g-', linewidth=1.5)
            ax.set_title(title, fontsize=12)
            ax.set_xlabel('Epoch')
            ax.set_ylabel('Value')
            ax.grid(True, alpha=0.3)
            # 标注最大值
            max_val = df[col].max()
            max_epoch = df[col].idxmax()
            ax.axhline(y=max_val, color='r', linestyle=':', alpha=0.5)
            ax.annotate(f'Best: {max_val:.4f} @ Epoch {max_epoch}',
                       xy=(max_epoch, max_val), fontsize=9,
                       bbox=dict(boxstyle='round,pad=0.3', facecolor='yellow', alpha=0.7))

    plt.tight_layout(rect=[0, 0, 1, 0.96])
    plt.savefig(str(save_dir / 'metrics_curves.png'), dpi=150, bbox_inches='tight')
    plt.close()

    # ---- 图3: 学习率曲线 ----
    lr_cols = [c for c in df.columns if c.startswith('lr/')]
    if lr_cols:
        fig, ax = plt.subplots(figsize=(10, 5))
        for col in lr_cols:
            ax.plot(epochs, df[col], label=col, linewidth=1.5)
        ax.set_title('Learning Rate Schedule', fontsize=14, fontweight='bold')
        ax.set_xlabel('Epoch')
        ax.set_ylabel('Learning Rate')
        ax.legend()
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(str(save_dir / 'learning_rate.png'), dpi=150, bbox_inches='tight')
        plt.close()


def run_train(
    dataset_yaml: str,
    output_dir: str,
    model_name: str = "yolo26s-seg",
    imgsz: int = 640,
    epochs: int = 150,
    batch_size: int = 16,
    patience: int = 0,
    device: str = "0",
    task_type: str = "seg",
    # ---- 数据增广参数 ----
    augment_hsv_h: float = 0.015,
    augment_hsv_s: float = 0.7,
    augment_hsv_v: float = 0.4,
    augment_degrees: float = 10.0,
    augment_translate: float = 0.1,
    augment_scale: float = 0.5,
    augment_shear: float = 5.0,
    augment_flipud: float = 0.5,
    augment_fliplr: float = 0.5,
    augment_mosaic: float = 0.3,
    augment_mixup: float = 0.1,
    augment_copy_paste: float = 0.5,
    augment_erasing: float = 0.0,
    close_mosaic: int = 50,
    # ---- 学习率参数 ----
    lr0: float = 0.01,
    lrf: float = 0.01,
    momentum: float = 0.937,
    weight_decay: float = 0.0005,
    warmup_epochs: float = 3.0,
    warmup_momentum: float = 0.8,
    # ---- 回调 ----
    epoch_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    progress_callback: Optional[Callable] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> dict:
    """
    执行 YOLO26s-seg 训练。

    Args:
        dataset_yaml: dataset.yaml 文件路径
        output_dir: 训练输出目录
        model_name: 模型名称（默认 yolo26s-seg）
        imgsz: 输入图像尺寸（默认 640）
        epochs: 训练轮数（默认 150）
        batch_size: 批大小（默认 16）
        patience: 早停耐心值（0 = 禁用早停）
        device: 训练设备（"0" = GPU 0, "cpu" = CPU）
        augment_*: 各项数据增广参数
        close_mosaic: 最后 N 个 epoch 关闭 Mosaic
        epoch_callback: 每个 epoch 结束后的回调函数，接收一个字典参数：
            {
                "epoch": int,           # 当前 epoch (从0开始)
                "total_epochs": int,    # 总 epoch 数
                "box_loss": float,      # Box Loss
                "seg_loss": float,      # Seg Loss
                "cls_loss": float,      # Cls Loss
                "dfl_loss": float,      # DFL Loss
                "total_loss": float,    # 总 Loss
                "precision_B": float,   # Box Precision
                "recall_B": float,      # Box Recall
                "mAP50_B": float,       # Box mAP@0.5
                "mAP50_95_B": float,    # Box mAP@0.5:0.95
                "precision_M": float,   # Mask Precision
                "recall_M": float,      # Mask Recall
                "mAP50_M": float,       # Mask mAP@0.5
                "mAP50_95_M": float,    # Mask mAP@0.5:0.95
                "best_fitness": float,  # 最佳 fitness
                "lr": float,            # 当前学习率
            }
        progress_callback: 进度回调

    Returns:
        训练结果字典
    """
    from ultralytics import YOLO

    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    # ---- 任务类型自动适配 ----
    # task_type='det' 时：
    #   - 默认模型若未指定 -seg，自动使用检测版（去掉 -seg 后缀）
    #   - close_mosaic 在小数据集下行为一致
    is_det = (task_type == "det")
    if is_det:
        # 用户传 yolo26s-seg → 自动改 yolo26n.pt（项目里有这个权重）
        # 用户传 yolo11s.pt 等 → 保持不变
        if "-seg" in model_name.lower():
            # 自动去掉 -seg 后缀，转为检测模型
            base = model_name.lower().replace("-seg", "").replace(".pt", "")
            # 优先使用项目根目录已有的 .pt（如 yolo26n.pt）
            local_pt = Path(__file__).parent.parent / f"{base}.pt"
            if local_pt.exists():
                model_name = str(local_pt)
            else:
                # fallback 使用 ultralytics 标准命名（自动下载）
                model_name = f"{base}.pt"
            print(f"[task_type=det] 自动切换检测模型: {model_name}")

    # ---- 加载预训练模型 ----
    model = YOLO(model_name)

    # ---- 注册取消检查回调 ----
    # 在每个 epoch 开始前/结束后 + 每隔 N 个 batch 检查是否被外部取消
    # 检测到取消时设置 trainer.stop=True，Ultralytics 训练循环会在 epoch 边界检查此标志并优雅退出
    if cancel_check is not None:
        _batch_check_interval = 20  # 每 20 个 batch 检查一次 DB（避免每个 batch 都查库）
        _batch_counter = {"n": 0}

        def _check_cancel(trainer):
            try:
                if cancel_check():
                    print("\n[训练取消] 检测到取消信号，将在当前 epoch 结束后停止训练\n")
                    trainer.stop = True
            except Exception as e:
                print(f"[cancel_check error] {e}")

        def _check_cancel_batch(trainer):
            _batch_counter["n"] += 1
            if _batch_counter["n"] % _batch_check_interval == 0:
                _check_cancel(trainer)

        model.add_callback("on_train_epoch_start", _check_cancel)
        model.add_callback("on_fit_epoch_end", _check_cancel)
        model.add_callback("on_train_batch_end", _check_cancel_batch)

    # ---- 注册 epoch 回调 ----
    if epoch_callback is not None:
        def _on_fit_epoch_end(trainer):
            """
            Ultralytics on_fit_epoch_end 回调。
            在每个 epoch 的训练+验证完成后触发。
            从 trainer 对象中提取关键指标，打包成字典传递给 GUI。
            """
            data = {
                "epoch": trainer.epoch,
                "total_epochs": trainer.epochs,
                "best_fitness": float(trainer.best_fitness) if trainer.best_fitness is not None else 0.0,
            }

            # ---- 提取 Train Loss ----
            # trainer.loss_items 是训练 loss (Tensor)
            if trainer.loss_items is not None:
                try:
                    loss_values = trainer.loss_items.cpu().tolist()
                    loss_names = trainer.loss_names if trainer.loss_names else []
                    for name, val in zip(loss_names, loss_values):
                        # 名称如 'box_loss', 'seg_loss', 'cls_loss', 'dfl_loss'
                        data[f"train_{name}"] = float(val)
                except Exception:
                    pass

            # 总 train loss
            if trainer.tloss is not None:
                try:
                    data["train_total_loss"] = float(trainer.tloss.cpu().item()) if hasattr(trainer.tloss, 'item') else float(trainer.tloss)
                except Exception:
                    data["train_total_loss"] = 0.0

            # ---- 提取 Val Loss ----
            # 方法1: 从 trainer.metrics 中获取（新版 Ultralytics）
            try:
                metrics = trainer.metrics if trainer.metrics else {}
                val_loss_keys = {
                    'val/box_loss': 'val_box_loss',
                    'val/seg_loss': 'val_seg_loss',
                    'val/cls_loss': 'val_cls_loss',
                    'val/dfl_loss': 'val_dfl_loss',
                }
                for src, dst in val_loss_keys.items():
                    if src in metrics:
                        data[dst] = float(metrics[src])
            except Exception:
                pass

            # 方法2: 从 trainer.validator.loss_items 获取（兼容旧版）
            if 'val_box_loss' not in data:
                try:
                    if hasattr(trainer, 'validator') and trainer.validator is not None:
                        if hasattr(trainer.validator, 'loss_items') and trainer.validator.loss_items is not None:
                            vl = trainer.validator.loss_items
                            val_loss_values = vl.cpu().tolist() if hasattr(vl, 'cpu') else list(vl)
                            loss_names = trainer.loss_names if trainer.loss_names else []
                            for name, val in zip(loss_names, val_loss_values):
                                data[f"val_{name}"] = float(val)
                except Exception:
                    pass

            # 方法3: 从 results.csv 最后一行读取
            if 'val_box_loss' not in data:
                try:
                    csv_path = Path(trainer.save_dir) / 'results.csv'
                    if csv_path.exists():
                        import pandas as pd
                        df = pd.read_csv(csv_path)
                        df.columns = df.columns.str.strip()
                        if len(df) > 0:
                            last = df.iloc[-1]
                            for col, key in [('val/box_loss','val_box_loss'),('val/seg_loss','val_seg_loss'),
                                             ('val/cls_loss','val_cls_loss'),('val/dfl_loss','val_dfl_loss')]:
                                if col in df.columns:
                                    data[key] = float(last[col])
                except Exception:
                    pass

            # ---- 提取验证指标 ----
            metrics = trainer.metrics if trainer.metrics else {}
            metric_mapping = {
                'metrics/precision(B)': 'precision_B',
                'metrics/recall(B)': 'recall_B',
                'metrics/mAP50(B)': 'mAP50_B',
                'metrics/mAP50-95(B)': 'mAP50_95_B',
                'metrics/precision(M)': 'precision_M',
                'metrics/recall(M)': 'recall_M',
                'metrics/mAP50(M)': 'mAP50_M',
                'metrics/mAP50-95(M)': 'mAP50_95_M',
            }
            for src_key, dst_key in metric_mapping.items():
                data[dst_key] = float(metrics.get(src_key, 0.0))

            # ---- 提取学习率 ----
            try:
                if trainer.optimizer and trainer.optimizer.param_groups:
                    data["lr"] = float(trainer.optimizer.param_groups[0]['lr'])
                else:
                    data["lr"] = 0.0
            except Exception:
                data["lr"] = 0.0

            # ---- 调用外部回调 ----
            epoch_callback(data)

        # 注册回调
        model.add_callback("on_fit_epoch_end", _on_fit_epoch_end)

    # ---- 开始训练 ----
    results = model.train(
        data=str(Path(dataset_yaml).resolve()),
        project=str(output_dir),
        name="train",
        exist_ok=True,
        imgsz=imgsz,
        epochs=epochs,
        batch=batch_size,
        patience=patience,
        device=device,
        workers=0,
        cache="ram",
        # 数据增广
        hsv_h=augment_hsv_h,
        hsv_s=augment_hsv_s,
        hsv_v=augment_hsv_v,
        degrees=augment_degrees,
        translate=augment_translate,
        scale=augment_scale,
        shear=augment_shear,
        flipud=augment_flipud,
        fliplr=augment_fliplr,
        mosaic=augment_mosaic,
        mixup=augment_mixup,
        copy_paste=augment_copy_paste,
        erasing=augment_erasing,
        close_mosaic=close_mosaic,
        # 学习率
        lr0=lr0,
        lrf=lrf,
        momentum=momentum,
        weight_decay=weight_decay,
        warmup_epochs=warmup_epochs,
        warmup_momentum=warmup_momentum,
        # 其他
        save=True,
        save_period=50,
        plots=True,
        verbose=True,
    )

    # ---- 返回结果 ----
    # Ultralytics 可能在 project/name/ 或 project/name/weights/ 下保存模型
    # 用 glob 搜索最可靠
    best_pt = None
    last_pt = None
    results_csv_path = None

    # 搜索 output_dir 下所有 best.pt
    for p in output_dir.rglob("best.pt"):
        best_pt = str(p)
        break
    for p in output_dir.rglob("last.pt"):
        last_pt = str(p)
        break
    for p in output_dir.rglob("results.csv"):
        results_csv_path = str(p)
        break

    # 绘制自定义训练曲线
    if results_csv_path:
        plots_dir = Path(results_csv_path).parent / "custom_plots"
        plot_training_curves(results_csv_path, str(plots_dir))

    return {
        "best_pt": best_pt,
        "last_pt": last_pt,
        "results_csv": results_csv_path,
        "train_dir": str(output_dir),
    }
