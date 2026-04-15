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

            # ── nncf / openvino 2024.x 兼容补丁 ────────────────────────────
            # openvino 2024.x 将完整 API 放在 openvino.runtime 下，
            # nncf 仍按旧约定直接访问 openvino.Node / import openvino.op 等。
            # 三步修复：
            #   1) 普通属性：从 openvino.runtime 批量 setattr 补到顶层
            #   2) 直接子模块：注册到 sys.modules（op / opset* …）
            #   3) utils 子模块：openvino.runtime.utils.* → openvino.utils.*
            # ────────────────────────────────────────────────────────────────
            import sys as _sys
            import importlib as _importlib
            import pkgutil as _pkgutil
            import openvino.runtime as _ovrt

            # 1) 补普通属性
            for _attr in dir(_ovrt):
                if not _attr.startswith('_') and not hasattr(openvino, _attr):
                    setattr(openvino, _attr, getattr(_ovrt, _attr))

            # 2) 补直接子模块（op / opset1-15 / opset_utils / exceptions）
            for _finder, _sm, _ispkg in _pkgutil.iter_modules(_ovrt.__path__):
                _ov_full  = f'openvino.{_sm}'
                _rt_full  = f'openvino.runtime.{_sm}'
                if _ov_full not in _sys.modules:
                    try:
                        _mod = _importlib.import_module(_rt_full)
                        _sys.modules[_ov_full] = _mod
                        setattr(openvino, _sm, _mod)
                    except ImportError:
                        pass

            # 3) 补 openvino.utils.* → openvino.runtime.utils.*
            #    openvino.utils 是 flat module（非包），子模块无法自动找到，
            #    手动注册到 sys.modules 并挂到 openvino.utils 属性上
            import openvino.utils as _ov_utils
            import openvino.runtime.utils as _rt_utils
            for _finder, _sm, _ispkg in _pkgutil.iter_modules(_rt_utils.__path__):
                _ov_sub = f'openvino.utils.{_sm}'
                _rt_sub = f'openvino.runtime.utils.{_sm}'
                if _ov_sub not in _sys.modules:
                    try:
                        _mod = _importlib.import_module(_rt_sub)
                        _sys.modules[_ov_sub] = _mod
                        setattr(_ov_utils, _sm, _mod)  # 支持 from openvino.utils import X
                    except ImportError:
                        pass

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
