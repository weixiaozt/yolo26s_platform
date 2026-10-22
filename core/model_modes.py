"""YOLO 双分支模型的默认推理模式；导出模型保持其固化的计算图。"""


def supports_native_head(model) -> bool:
    """通过真实检测头判断能力，兼容被另存为 best.pt 的模型。"""
    network = getattr(model, "model", None)
    layers = getattr(network, "model", None)
    if layers is None:
        return False
    try:
        head = layers[-1]
    except (IndexError, KeyError, TypeError):
        return False
    return hasattr(head, "one2one_cv2") and hasattr(head, "one2one_cv3")


def use_native_pytorch_head(model):
    """只给可切换的 PyTorch 双分支模型设置原生模式。"""
    if supports_native_head(model):
        model.model.end2end = True
        # Predictor 初始化时会读取 overrides，避免沿用权重里保存的兼容设置。
        model.overrides["end2end"] = True
    return model
