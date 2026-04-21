# -*- coding: utf-8 -*-
"""
模型导出模块 (export.py)
=========================
功能：将训练好的 .pt 模型导出为部署格式。
支持的导出格式：
    - ONNX：通用中间格式
    - OpenVINO：Intel CPU/GPU/NPU 推断加速
    - TensorRT：NVIDIA GPU 推断加速（需要 GPU 环境）

注意事项：
    - OpenVINO 导出不需要 GPU
    - TensorRT 导出需要 NVIDIA GPU 和 tensorrt 库
    - 导出时使用固定输入尺寸（默认 640x640）
"""

from pathlib import Path
from typing import Optional, Callable


def _fix_openvino_compat():
    """OpenVINO 2026+ 移除了 openvino.runtime，注册兼容别名"""
    try:
        import openvino
        import sys
        if 'openvino.runtime' not in sys.modules:
            sys.modules['openvino.runtime'] = openvino
    except ImportError:
        pass


def run_export(
    model_path: str,
    output_dir: str,
    export_format: str = "openvino",
    imgsz: int = 640,
    half: bool = False,
    int8: bool = False,
    simplify: bool = True,
    device: str = None,
    dataset_path: str = None,
    progress_callback: Optional[Callable] = None
) -> dict:
    """
    导出模型到指定格式。

    Args:
        model_path: 训练好的 .pt 模型路径
        output_dir: 导出文件保存目录
        export_format: 导出格式，可选 "onnx" / "openvino" / "tensorrt"
        imgsz: 输入图像尺寸（默认 640）
        half: 是否使用 FP16 半精度（TensorRT 推荐开启，OpenVINO 慎用）
        simplify: 是否简化 ONNX 模型（默认 True）
        device: 导出设备（OpenVINO 有效），如 "cpu", "gpu", "gpu.0", "npu", "auto"
        dataset_path: 数据集路径（可选），用于 INT8 量化校准
        progress_callback: 进度回调

    Returns:
        导出结果字典：
        {
            "format": str,          # 导出格式
            "onnx_path": str,       # ONNX 文件路径（如果有）
            "export_path": str,     # 最终导出文件/目录路径
            "imgsz": int,           # 输入尺寸
        }
    """
    from ultralytics import YOLO

    model_path = Path(model_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    assert model_path.exists(), f"模型文件不存在: {model_path}"

    # ---- 加载模型 ----
    if progress_callback:
        progress_callback(1, 4, "加载模型...")
    model = YOLO(str(model_path))

    results = {
        "format": export_format,
        "imgsz": imgsz,
        "onnx_path": None,
        "export_path": None,
    }

    # ---- 第一步：始终先导出 ONNX ----
    if progress_callback:
        progress_callback(2, 4, "导出 ONNX...")

    try:
        # 分割模型导出时 simplify 可能导致问题，提供备选方案
        try:
            onnx_path = model.export(
                format="onnx",
                imgsz=imgsz,
                simplify=simplify,
                half=False,  # ONNX 通常用 FP32
            )
        except Exception as simplify_error:
            if simplify and "simplify" in str(simplify_error).lower():
                if progress_callback:
                    progress_callback(2, 4, "ONNX slimming 失败，尝试不简化...")
                onnx_path = model.export(
                    format="onnx",
                    imgsz=imgsz,
                    simplify=False,  # 禁用简化
                    half=False,
                )
            else:
                raise
        results["onnx_path"] = str(onnx_path)
    except Exception as e:
        error_msg = str(e)
        if "No module named" in error_msg and "onnx" in error_msg.lower():
            raise RuntimeError(
                f"ONNX 导出失败: {error_msg}\n"
                "请确保已安装 ONNX:\n"
                "  pip install onnx>=1.14.0 onnxsim"
            )
        else:
            raise RuntimeError(f"ONNX 导出失败: {error_msg}")

    # ---- 第二步：根据目标格式进一步导出 ----
    if export_format == "onnx":
        # 只需要 ONNX，已经完成
        results["export_path"] = str(onnx_path)

    elif export_format == "openvino":
        if progress_callback:
            progress_callback(3, 4, "导出 OpenVINO...")

        try:
            # 检查 OpenVINO 是否已安装
            try:
                import openvino
            except ImportError:
                raise RuntimeError(
                    "OpenVINO 库未安装。请运行: pip install openvino>=2024.0"
                )

            # OpenVINO 2026+ 兼容修复
            _fix_openvino_compat()

            # 重新加载模型导出 OpenVINO
            model2 = YOLO(str(model_path))
            
            # 准备导出参数
            # 注意：model.export() 的 device 参数是指 PyTorch 设备 (cpu/0/1)
            # 不是 OpenVINO 设备，所以不传递 device 参数
            if int8:
                # ---- INT8 量化导出 ----
                # 检查 NNCF 依赖
                try:
                    import nncf  # noqa
                except ImportError:
                    raise RuntimeError(
                        "INT8 量化需要安装 nncf 库:\n"
                        "  pip install nncf"
                    )
                # 找到 dataset.yaml 路径
                if not dataset_path:
                    raise RuntimeError(
                        "INT8 量化需要提供校准数据集目录（即训练时的 dataset.yaml 所在目录）"
                    )
                from pathlib import Path as _Path
                import glob as _glob
                _ds = _Path(dataset_path)
                if _ds.is_dir():
                    # 优先找名为 dataset.yaml 的文件
                    _candidates = list(_ds.glob("dataset.yaml")) or list(_ds.glob("*.yaml"))
                    if not _candidates:
                        raise RuntimeError(
                            f"在目录 {dataset_path} 中未找到 .yaml 文件\n"
                            "请选择包含 dataset.yaml 的数据集目录"
                        )
                    dataset_yaml_path = str(_candidates[0])
                else:
                    dataset_yaml_path = str(_ds)  # 直接是 yaml 文件

                export_kwargs = {
                    "format": "openvino",
                    "imgsz": imgsz,
                    "int8": True,
                    "data": dataset_yaml_path,  # 校准数据集
                }
            else:
                # ---- FP32 / FP16 导出 ----
                export_kwargs = {
                    "format": "openvino",
                    "imgsz": imgsz,
                    "half": half,
                }

            ov_path = model2.export(**export_kwargs)
            results["export_path"] = str(ov_path)
            
        except Exception as e:
            results["export_path"] = None
            error_msg = str(e)
            
            # 提供更有帮助的错误信息
            if "No module named" in error_msg or "openvino" in error_msg.lower():
                results["error"] = (
                    f"OpenVINO 导出失败: {error_msg}\n"
                    "请确保已安装 OpenVINO:\n"
                    "  pip install openvino>=2024.0"
                )
            elif "memory" in error_msg.lower() or "out of" in error_msg.lower():
                results["error"] = (
                    f"OpenVINO 导出失败: 内存不足\n"
                    f"详细错误: {error_msg}\n"
                    "建议:\n"
                    "  1. 关闭其他占用内存的程序\n"
                    "  2. 减小输入尺寸 (imgsz)\n"
                    "  3. 使用 FP32 代替 FP16"
                )
            else:
                results["error"] = (
                    f"OpenVINO 导出失败: {error_msg}\n"
                    "建议:\n"
                    "  1. 确保模型文件未损坏\n"
                    "  2. 尝试先导出 ONNX 格式测试\n"
                    "  3. 检查 OpenVINO 版本兼容性"
                )

    elif export_format == "tensorrt":
        if progress_callback:
            progress_callback(3, 4, "导出 TensorRT（需要 GPU）...")

        try:
            model3 = YOLO(str(model_path))
            trt_path = model3.export(
                format="engine",
                imgsz=imgsz,
                half=half,
                simplify=simplify,
            )
            results["export_path"] = str(trt_path)
        except Exception as e:
            results["export_path"] = None
            results["error"] = (
                f"TensorRT 导出失败: {str(e)}\n"
                "请确保：\n"
                "  1. 当前环境有 NVIDIA GPU\n"
                "  2. 已安装 tensorrt 库: pip install tensorrt\n"
                "  3. CUDA 版本与 tensorrt 兼容\n"
                "您可以使用已导出的 ONNX 文件，在目标机器上用 trtexec 转换：\n"
                f"  trtexec --onnx={onnx_path} --saveEngine=best.engine --fp16"
            )

    else:
        raise ValueError(f"不支持的导出格式: {export_format}，可选: onnx / openvino / tensorrt")

    # ---- 移动导出文件到指定目录 ----
    if progress_callback:
        progress_callback(4, 4, "整理导出文件...")

    # Ultralytics 默认将导出文件保存在 .pt 同级目录，需要移动到用户指定目录
    # 这里我们记录路径，由调用方决定是否移动

    return results
