# -*- coding: utf-8 -*-
"""推断服务 API（支持 .pt / ONNX / OpenVINO / TensorRT）"""

import sys
import uuid
import base64
from pathlib import Path

import cv2
import numpy as np
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..config import settings
from ..models.train_task import TrainTask
from ..models.inference_result import InferenceResult
from ..models.exported_model import ExportedModel
from ..models.defect_class import DefectClass
from ..models.project import Project

_root = str(Path(__file__).parent.parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

router = APIRouter(prefix="/api/inference", tags=["推断服务"])
_model_cache: dict = {}


def _get_model(model_path: str):
    """加载模型（LRU 缓存，容量 4）。"""
    if model_path in _model_cache:
        # LRU：命中后挪到队尾，避免被错误淘汰
        _model_cache[model_path] = _model_cache.pop(model_path)
        return _model_cache[model_path]
    # OpenVINO 2026+ 兼容修复
    if "openvino" in model_path.lower():
        try:
            import sys as _sys, openvino as _ov
            if 'openvino.runtime' not in _sys.modules:
                _sys.modules['openvino.runtime'] = _ov
        except ImportError:
            pass
    from ultralytics import YOLO
    model = YOLO(model_path)
    _model_cache[model_path] = model
    if len(_model_cache) > 4:
        _model_cache.pop(next(iter(_model_cache)))
    return model


@router.get("/models")
def list_models(project_id: int = Query(default=0), db: Session = Depends(get_db)):
    """列出项目下可用模型（.pt + 导出格式）"""
    models = []
    # PyTorch .pt 模型
    q = db.query(TrainTask).filter(TrainTask.status == "completed")
    if project_id > 0:
        q = q.filter(TrainTask.project_id == project_id)
    tasks = q.order_by(TrainTask.finished_at.desc()).all()
    task_ids = [t.id for t in tasks]
    for t in tasks:
        if t.best_model_path:
            models.append({"task_id": t.id, "model_format": "pytorch",
                "label": f"{t.task_name} — best.pt", "model_path": t.best_model_path})
        if t.last_model_path:
            models.append({"task_id": t.id, "model_format": "pytorch",
                "label": f"{t.task_name} — last.pt", "model_path": t.last_model_path})
    # 导出的模型（只显示当前项目的）
    eq = db.query(ExportedModel).filter(ExportedModel.status == "completed", ExportedModel.export_path.isnot(None))
    if task_ids:
        eq = eq.filter(ExportedModel.task_id.in_(task_ids))
    elif project_id > 0:
        eq = eq.filter(False)  # 项目下没有训练任务，不显示导出模型
    exports = eq.order_by(ExportedModel.created_at.desc()).all()
    fmt_map = {"onnx": "ONNX", "openvino": "OpenVINO", "tensorrt": "TensorRT"}
    for e in exports:
        t = db.query(TrainTask).filter(TrainTask.id == e.task_id).first()
        tname = t.task_name if t else f"Task#{e.task_id}"
        fp = "FP16" if e.half else "FP32"
        models.append({"task_id": e.task_id, "model_format": e.export_format,
            "label": f"{tname} — {e.source_type}.{fmt_map.get(e.export_format, e.export_format)} ({fp})",
            "model_path": e.export_path})
    return models


@router.get("/devices")
def list_devices():
    """检测可用推断设备"""
    devices = [{"id": "cpu", "name": "CPU", "available": True}]
    try:
        import torch
        if torch.cuda.is_available():
            for i in range(torch.cuda.device_count()):
                devices.append({"id": str(i), "name": f"NVIDIA {torch.cuda.get_device_name(i)}", "available": True})
        else:
            devices.append({"id": "0", "name": "NVIDIA GPU (不可用)", "available": False})
    except Exception:
        devices.append({"id": "0", "name": "NVIDIA GPU (未安装)", "available": False})
    return devices


def _resolve_class_names(model, project_id: int, db) -> dict:
    """
    类别名映射 (class_index → name)，model.names 优先。

    cls 训练走 ImageFolder，类别 index 是子目录字典序（如 Broken=0, Crack=1, OK=2），
    与 DB class_index（创建顺序）可能不同；用 DB 映射会把 OK 显示成 Crack。
    seg/det/obb 的 dataset.yaml 按 DB class_index 写，两边一致。
    """
    cn = {}
    mn = getattr(model, "names", None)
    if mn:
        try:
            cn = {int(k): str(v) for k, v in (mn.items() if isinstance(mn, dict) else enumerate(mn))}
        except Exception:
            cn = {}
    if not cn and project_id and project_id > 0:
        try:
            dcs = db.query(DefectClass).filter(DefectClass.project_id == project_id).all()
            cn = {int(dc.class_index): dc.name for dc in dcs}
        except Exception:
            pass
    return cn


def _run_obb_inference(model, img_array, filename, project_id, task_id, conf, iou, device, db):
    """
    OBB 推断：返回每个目标的 4 角点 polygon（图像像素坐标）+ 类别 + 置信度。
    在原图上画旋转四边形作为 overlay。
    """
    import time
    t0 = time.time()
    pred = model.predict(
        img_array, verbose=False,
        conf=conf or 0.25, iou=iou or 0.5,
        device=device if device != "cpu" else "cpu",
    )
    elapsed = time.time() - t0

    r0 = pred[0] if pred else None
    obb = getattr(r0, "obb", None) if r0 is not None else None

    detections = []
    if obb is not None and obb.xyxyxyxy is not None and len(obb) > 0:
        # xyxyxyxy: (N, 4, 2) 图像像素坐标
        polys = obb.xyxyxyxy.cpu().numpy() if hasattr(obb.xyxyxyxy, "cpu") else obb.xyxyxyxy
        cls_ids = obb.cls.cpu().numpy().astype(int) if hasattr(obb.cls, "cpu") else obb.cls
        confs = obb.conf.cpu().numpy() if hasattr(obb.conf, "cpu") else obb.conf

        cn = _resolve_class_names(model, project_id, db)
        for poly, cid, cf in zip(polys, cls_ids, confs):
            cid = int(cid)
            pts = [{"x": float(p[0]), "y": float(p[1])} for p in poly]
            xs = [p["x"] for p in pts]
            ys = [p["y"] for p in pts]
            detections.append({
                "class_id": cid,
                "class_name": cn.get(cid, f"C{cid}"),
                "confidence": round(float(cf), 4),
                # 4 点旋转矩形（前端连线即可）
                "polygon": pts,
                # 同时给一个轴对齐外接矩形做兼容（不影响 OBB 显示）
                "bbox": {"x1": int(min(xs)), "y1": int(min(ys)),
                         "x2": int(max(xs)), "y2": int(max(ys))},
            })

    # ---- 在原图上画旋转四边形作为 overlay ----
    overlay = img_array.copy()
    if overlay.ndim == 2:
        overlay = cv2.cvtColor(overlay, cv2.COLOR_GRAY2BGR)
    elif overlay.shape[2] == 4:
        overlay = cv2.cvtColor(overlay, cv2.COLOR_BGRA2BGR)

    # 用类别 id 决定颜色（BGR）
    palette = [(76,76,255),(76,255,103),(45,165,230),(255,144,76),(204,128,189),
               (193,166,12),(193,89,89),(0,128,255),(128,255,128)]

    for det in detections:
        color = palette[det["class_id"] % len(palette)]
        pts = np.array([[p["x"], p["y"]] for p in det["polygon"]], dtype=np.int32)
        cv2.polylines(overlay, [pts], isClosed=True, color=color, thickness=2)
        # 标签框（用第一个点上方）
        label = f"{det['class_name']} {det['confidence']:.2f}"
        x0, y0 = int(pts[0][0]), int(pts[0][1])
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
        cv2.rectangle(overlay, (x0, max(0, y0 - th - 4)), (x0 + tw + 4, y0), color, -1)
        cv2.putText(overlay, label, (x0 + 2, max(th, y0 - 2)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)

    # ---- 保存图片（original + overlay） ----
    infer_dir = settings.runs_path / "inference"
    infer_dir.mkdir(parents=True, exist_ok=True)
    rid = uuid.uuid4().hex[:12]
    cv2.imwrite(str(infer_dir / f"{rid}_original.png"), img_array)
    cv2.imwrite(str(infer_dir / f"{rid}_overlay.png"), overlay)
    url_pfx = "/static/storage/runs/inference"

    record = InferenceResult(
        project_id=project_id, task_id=task_id,
        filename=filename or "unknown", device=device,
        conf_thresh=conf, iou_thresh=iou, resize_size=0,
        num_detections=len(detections),
        inference_time=round(elapsed, 3),
        detections=detections,
        original_path=f"{url_pfx}/{rid}_original.png",
        overlay_path=f"{url_pfx}/{rid}_overlay.png",
    )
    db.add(record); db.commit(); db.refresh(record)

    return {
        "id": record.id,
        "task_type": "obb",
        "filename": record.filename,
        "device": record.device,
        "num_detections": record.num_detections,
        "inference_time": record.inference_time,
        "detections": detections,
        "original_url": record.original_path,
        "overlay_url": record.overlay_path,
        "overlay_morph_url": None,
        "mask_url": "",
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


def _run_cls_inference(model, img_array, content, filename, project_id, task_id, device, db):
    """分类推断：返回 top-1 类别 + top-5 概率"""
    import time
    t0 = time.time()
    # YOLO classify 直接接受图片数组，会自动 resize 到模型 imgsz
    results = model.predict(img_array, verbose=False, device=device if device != "cpu" else "cpu")
    elapsed = time.time() - t0

    r0 = results[0] if results else None
    top1_id = -1
    top1_conf = 0.0
    top5 = []  # [{class_id, class_name, confidence}]

    if r0 is not None and getattr(r0, "probs", None) is not None:
        probs = r0.probs
        top1_id = int(probs.top1) if hasattr(probs, "top1") else -1
        top1_conf = float(probs.top1conf) if hasattr(probs, "top1conf") else 0.0
        # top-5
        if hasattr(probs, "top5") and hasattr(probs, "top5conf"):
            ids = probs.top5
            confs = probs.top5conf.cpu().numpy().tolist() if hasattr(probs.top5conf, "cpu") else list(probs.top5conf)
            for cid, conf in zip(ids, confs):
                top5.append({"class_id": int(cid), "confidence": round(float(conf), 4)})

    # 类别名映射（DB 找不到时用 model.names 兜底）
    class_names = _resolve_class_names(model, project_id, db)
    for d in top5:
        d["class_name"] = class_names.get(d["class_id"], f"C{d['class_id']}")
    top1_name = class_names.get(top1_id, f"C{top1_id}")

    # 保存原图（cls 不需要 overlay/mask）
    infer_dir = settings.runs_path / "inference"
    infer_dir.mkdir(parents=True, exist_ok=True)
    rid = uuid.uuid4().hex[:12]
    cv2.imwrite(str(infer_dir / f"{rid}_original.png"), img_array)
    url_pfx = "/static/storage/runs/inference"

    # 复用 InferenceResult 表（detections 字段存 top5）
    record = InferenceResult(
        project_id=project_id, task_id=task_id,
        filename=filename or "unknown", device=device,
        conf_thresh=0.0, iou_thresh=0.0, resize_size=0,
        num_detections=1 if top1_id >= 0 else 0,
        inference_time=round(elapsed, 3),
        detections=top5,
        original_path=f"{url_pfx}/{rid}_original.png",
    )
    db.add(record); db.commit(); db.refresh(record)

    return {
        "id": record.id,
        "task_type": "cls",
        "filename": record.filename,
        "device": record.device,
        "inference_time": record.inference_time,
        "num_detections": record.num_detections,
        # 与 seg/det 保持兼容：detections 里就是 top5（无 bbox）
        "detections": top5,
        "top1": {"class_id": top1_id, "class_name": top1_name, "confidence": round(top1_conf, 4)},
        "top5": top5,
        "original_url": record.original_path,
        # cls 没有这些图，保持字段存在以兼容前端类型
        "overlay_url": "",
        "overlay_morph_url": None,
        "mask_url": "",
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


def _resolve_model_path(model_path: str, task_id: int, db: Session) -> str:
    mp = model_path
    if not mp and task_id > 0:
        task = db.query(TrainTask).filter(TrainTask.id == task_id).first()
        if task and task.best_model_path:
            mp = task.best_model_path
    if not mp or not Path(mp).exists():
        raise HTTPException(status_code=404, detail="模型文件不存在")
    return mp


def _run_inference_core(
    img_array, content: bytes, filename: str,
    project_id: int, task_id: int, mp: str,
    conf: float, iou: float, resize_size: int, device: str,
    db: Session,
) -> dict:
    """
    共用推理核心：根据 TrainTask.config.task_type 路由到 cls / obb / seg-det。
    /run 和 /run-by-image-id 共有的逻辑（任务配置 → 路由 → 持久化）抽出来。
    """
    crop_size, overlap = 640, 0.2
    use_morphology, dilate_kernel, erode_kernel = False, 3, 3
    task_type = "seg"
    if task_id > 0:
        task = db.query(TrainTask).filter(TrainTask.id == task_id).first()
        if task and task.config:
            crop_size = task.config.get("crop_size", 640)
            overlap = task.config.get("overlap", 0.2)
            use_morphology = task.config.get("use_morphology", False)
            dilate_kernel = task.config.get("dilate_kernel", 3)
            erode_kernel = task.config.get("erode_kernel", 3)
            task_type = task.config.get("task_type", "seg")
        if not project_id and task:
            project_id = task.project_id

    model = _get_model(mp)

    # 分类：整图 letterbox 到 imgsz；不滑窗
    if task_type == "cls":
        return _run_cls_inference(
            model=model, img_array=img_array, content=content,
            filename=filename, project_id=project_id, task_id=task_id,
            device=device, db=db,
        )
    # OBB：整图，输出 4 角点 polygon
    if task_type == "obb":
        return _run_obb_inference(
            model=model, img_array=img_array, filename=filename,
            project_id=project_id, task_id=task_id,
            conf=conf, iou=iou, device=device, db=db,
        )

    # seg / det 走滑窗
    from core.inference import infer_single_image
    result = infer_single_image(
        model=model, image=img_array,
        crop_size=crop_size, overlap=overlap,
        conf_thresh=conf, iou_thresh=iou,
        resize_size=resize_size if resize_size > 0 else None,
        device=device,
        use_morphology=use_morphology,
        dilate_kernel=dilate_kernel,
        erode_kernel=erode_kernel,
    )

    # 保存到磁盘
    infer_dir = settings.runs_path / "inference"
    infer_dir.mkdir(parents=True, exist_ok=True)
    rid = uuid.uuid4().hex[:12]
    save_list = [("original", img_array), ("overlay", result["overlay"]), ("mask", result["mask_image"])]
    if result.get("overlay_morph") is not None:
        save_list.append(("overlay_morph", result["overlay_morph"]))
    for name, img in save_list:
        cv2.imwrite(str(infer_dir / f"{rid}_{name}.png"), img)
    url_pfx = "/static/storage/runs/inference"

    # 加载类别名称映射（DB 找不到时用 model.names 兜底）
    class_names = _resolve_class_names(model, project_id, db)

    # 检测列表
    detections = []
    for i in range(result["num_detections"]):
        box = result["boxes"][i]
        cid = int(result["classes"][i])
        detections.append({
            "class_id": cid,
            "class_name": class_names.get(cid, f"C{cid}"),
            "confidence": round(float(result["scores"][i]), 4),
            "bbox": {"x1": int(box[0]), "y1": int(box[1]), "x2": int(box[2]), "y2": int(box[3])},
        })

    # 持久化
    record = InferenceResult(
        project_id=project_id, task_id=task_id,
        filename=filename, device=device,
        conf_thresh=conf, iou_thresh=iou, resize_size=resize_size,
        num_detections=result["num_detections"],
        inference_time=round(result.get("inference_time", 0), 3),
        detections=detections,
        original_path=f"{url_pfx}/{rid}_original.png",
        overlay_path=f"{url_pfx}/{rid}_overlay.png",
        overlay_morph_path=f"{url_pfx}/{rid}_overlay_morph.png" if result.get("overlay_morph") is not None else None,
        mask_path=f"{url_pfx}/{rid}_mask.png",
    )
    db.add(record); db.commit(); db.refresh(record)

    return {
        "id": record.id,
        "task_type": task_type,
        "num_detections": record.num_detections,
        "inference_time": record.inference_time,
        "detections": detections,
        "filename": record.filename,
        "device": record.device,
        "original_url": record.original_path,
        "overlay_url": record.overlay_path,
        "overlay_morph_url": f"{url_pfx}/{rid}_overlay_morph.png" if result.get("overlay_morph") is not None else None,
        "mask_url": record.mask_path,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


@router.post("/run")
async def run_inference(
    file: UploadFile = File(...),
    project_id: int = Form(default=0),
    task_id: int = Form(default=0),
    model_path: str = Form(default=""),
    conf: float = Form(default=0.15),
    iou: float = Form(default=0.5),
    resize_size: int = Form(default=0),
    device: str = Form(default="cpu"),
    db: Session = Depends(get_db),
):
    """单张推断 + 持久化（multipart 上传图片）"""
    mp = _resolve_model_path(model_path, task_id, db)
    content = await file.read()
    img_array = cv2.imdecode(np.frombuffer(content, np.uint8), cv2.IMREAD_UNCHANGED)
    if img_array is None:
        raise HTTPException(status_code=400, detail="无法读取图像")
    return _run_inference_core(
        img_array=img_array, content=content,
        filename=file.filename or "unknown",
        project_id=project_id, task_id=task_id, mp=mp,
        conf=conf, iou=iou, resize_size=resize_size, device=device, db=db,
    )


@router.post("/run-by-image-id")
def run_inference_by_image_id(
    image_id: int = Form(...),
    project_id: int = Form(default=0),
    task_id: int = Form(default=0),
    model_path: str = Form(default=""),
    conf: float = Form(default=0.15),
    iou: float = Form(default=0.5),
    resize_size: int = Form(default=0),
    device: str = Form(default="cpu"),
    db: Session = Depends(get_db),
):
    """
    按 image_id 推断（"推理训练图"批量场景）。
    直接从本地读文件，跳过 multipart 上传，避免前端"下载→再上传"的浪费。
    返回里多带 source_image_id / source_class_id 给前端核对 ground truth。
    """
    from ..models.image import Image as ImageModel

    image = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not image:
        raise HTTPException(404, "图像不存在")
    if not project_id:
        project_id = image.project_id

    fp = Path(image.file_path)
    if not fp.is_absolute():
        fp = settings.upload_path / image.file_path
    if not fp.exists():
        raise HTTPException(404, f"图像文件不存在: {fp}")

    mp = _resolve_model_path(model_path, task_id, db)
    content = fp.read_bytes()
    img_array = cv2.imdecode(np.frombuffer(content, np.uint8), cv2.IMREAD_UNCHANGED)
    if img_array is None:
        raise HTTPException(400, "无法读取图像")

    result = _run_inference_core(
        img_array=img_array, content=content,
        filename=image.filename or fp.name,
        project_id=project_id, task_id=task_id, mp=mp,
        conf=conf, iou=iou, resize_size=resize_size, device=device, db=db,
    )
    result["source_image_id"] = image_id
    result["source_class_id"] = image.class_id
    return result


@router.get("/project-images")
def list_project_images_for_inference(
    project_id: int = Query(...),
    status: str = Query(default="labeled", description="labeled / reviewed / all"),
    class_id: int | None = Query(default=None, description="按 class_id 过滤（cls 项目）"),
    limit: int = Query(default=100, ge=1, le=2000),
    sample: bool = Query(default=True, description="True=随机抽样, False=按创建时间倒序"),
    db: Session = Depends(get_db),
):
    """
    返回项目下用于"推理训练图"的图片列表（仅 id + filename + class_id）。
    前端拿到列表后循环调 /run-by-image-id。
    """
    from ..models.image import Image as ImageModel

    q = db.query(ImageModel).filter(ImageModel.project_id == project_id)
    if status == "labeled":
        q = q.filter(ImageModel.status.in_(["labeled", "reviewed"]))
    elif status == "reviewed":
        q = q.filter(ImageModel.status == "reviewed")
    if class_id is not None:
        q = q.filter(ImageModel.class_id == class_id)

    total = q.count()
    if sample:
        # MySQL: ORDER BY RAND() — 单查询完成抽样，不再把所有 id 拉到 Python
        items = q.order_by(func.rand()).limit(limit).all()
    else:
        items = q.order_by(ImageModel.created_at.desc()).limit(limit).all()

    return {
        "total": total,
        "returned": len(items),
        "items": [
            {"id": img.id, "filename": img.filename, "class_id": img.class_id, "status": img.status}
            for img in items
        ],
    }


@router.get("/history")
def list_history(project_id: int = Query(default=0), page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200), db: Session = Depends(get_db)):
    q = db.query(InferenceResult)
    if project_id > 0: q = q.filter(InferenceResult.project_id == project_id)
    total = q.count()
    items = q.order_by(InferenceResult.created_at.desc()).offset((page-1)*page_size).limit(page_size).all()

    # 加载类别名称映射（按 project_id 分组缓存）
    cn_cache: dict = {}
    def get_class_names(pid: int) -> dict:
        if pid not in cn_cache:
            dcs = db.query(DefectClass).filter(DefectClass.project_id == pid).all()
            cn_cache[pid] = {dc.class_index: dc.name for dc in dcs}
        return cn_cache[pid]

    def enrich(dets, pid):
        if not dets: return []
        names = get_class_names(pid) if pid else {}
        for d in dets:
            if "class_name" not in d or not d.get("class_name"):
                cid = d.get("class_id", 0)
                d["class_name"] = names.get(cid, f"C{cid}")
        return dets

    # task_type 缓存（按 task_id 查 TrainTask.config）
    tt_cache: dict = {}
    def get_task_type(tid: int) -> str:
        if tid in tt_cache:
            return tt_cache[tid]
        tt = "seg"
        if tid:
            t = db.query(TrainTask).filter(TrainTask.id == tid).first()
            if t and t.config:
                tt = t.config.get("task_type", "seg")
        tt_cache[tid] = tt
        return tt

    def infer_task_type(r) -> str:
        """优先从 TrainTask.config 取；取不到时根据 detections 字段兜底判断"""
        tt = get_task_type(r.task_id) if r.task_id else None
        if tt:
            return tt
        dets = r.detections or []
        if dets:
            d0 = dets[0]
            if "polygon" in d0 and isinstance(d0.get("polygon"), list) and len(d0.get("polygon")) == 4:
                return "obb"
            if "bbox" not in d0:
                return "cls"
        return "seg"

    return {"total": total, "page": page, "page_size": page_size, "items": [
        {"id": r.id, "filename": r.filename, "num_detections": r.num_detections,
         "inference_time": r.inference_time, "device": r.device,
         "task_type": infer_task_type(r),
         "detections": enrich(r.detections or [], r.project_id),
         "original_url": r.original_path or "", "overlay_url": r.overlay_path or "",
         "overlay_morph_url": r.overlay_morph_path,
         "mask_url": r.mask_path or "", "created_at": r.created_at.isoformat() if r.created_at else None}
        for r in items]}


def _url_to_disk(url: str) -> Path:
    return Path(settings.STORAGE_ROOT).resolve() / url.replace("/static/storage/", "")


@router.delete("/history/{rid}")
def del_history(rid: int, db: Session = Depends(get_db)):
    r = db.query(InferenceResult).filter(InferenceResult.id == rid).first()
    if not r: raise HTTPException(404, "不存在")
    for p in [r.original_path, r.overlay_path, r.mask_path]:
        if p:
            fp = _url_to_disk(p)
            if fp.exists(): fp.unlink()
    db.delete(r); db.commit()
    return {"ok": True}


@router.delete("/history")
def clear_history(project_id: int = Query(default=0), db: Session = Depends(get_db)):
    q = db.query(InferenceResult)
    if project_id > 0: q = q.filter(InferenceResult.project_id == project_id)
    recs = q.all()
    for r in recs:
        for p in [r.original_path, r.overlay_path, r.mask_path]:
            if p:
                fp = _url_to_disk(p)
                if fp.exists(): fp.unlink()
        db.delete(r)
    db.commit()
    return {"ok": True, "deleted": len(recs)}


# ============================================================
# 缺陷小图切割（仅 seg 项目，给二级分类模型当训练集）
# ============================================================

def _crop_defect_for_classifier(img, bbox, target_min: int = 128, target_max: int = 512):
    """
    按规则切单个缺陷小图。

    规则：
    - 长边 > target_max:  以 bbox 中心切 long×long 正方形 → resize 到 target_max
    - 长边 < target_min:  以 bbox 中心切 target_min×target_min（不缩放，向外膨胀）
    - 中间:               以 bbox 中心切 long×long 正方形（不缩放，按长边补正方形）
    边缘越界时窗口往内推保完整；fallback：side 不超过原图最小边。

    Args:
        img: 原图 ndarray
        bbox: dict {x1, y1, x2, y2}（推理 detection 里的格式）

    Returns:
        (crop_ndarray, output_size)  — output_size 用于命名
    """
    H, W = img.shape[:2]
    x1, y1 = int(bbox["x1"]), int(bbox["y1"])
    x2, y2 = int(bbox["x2"]), int(bbox["y2"])
    w = max(1, x2 - x1)
    h = max(1, y2 - y1)
    long_edge = max(w, h)
    cx = (x1 + x2) // 2
    cy = (y1 + y2) // 2

    side = max(long_edge, target_min)
    side = min(side, min(W, H))  # fallback：原图比目标还小

    # 居中切窗口；超边时往内推
    x0 = max(0, min(cx - side // 2, W - side))
    y0 = max(0, min(cy - side // 2, H - side))
    crop = img[y0:y0 + side, x0:x0 + side]

    if long_edge > target_max:
        crop = cv2.resize(crop, (target_max, target_max), interpolation=cv2.INTER_AREA)
        return crop, target_max
    return crop, side


@router.post("/crop-defects")
def crop_defects_for_classifier(
    project_id: int = Query(...),
    db: Session = Depends(get_db),
):
    """
    遍历项目所有推理记录，按缺陷 bbox 切小图，按类别打包成 zip 下载。

    仅适用于 seg 项目（其他 task_type 返回 400）。
    用途：给二级分类模型当训练集 — 解压后每个类别一个文件夹，可直接喂 yolo-cls。

    切图规则见 _crop_defect_for_classifier。
    命名: <类别名>/<类别名>_<输出尺寸>_<序号>.<原图扩展名>
    """
    import io
    import zipfile

    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, "项目不存在")
    if project.task_type != "seg":
        raise HTTPException(400, f"仅实例分割项目支持切割小图，当前 task_type={project.task_type}")

    records = (
        db.query(InferenceResult)
        .filter(InferenceResult.project_id == project_id)
        .order_by(InferenceResult.created_at)
        .all()
    )
    if not records:
        raise HTTPException(400, "项目下没有推理记录，先做推理")

    counters: dict = {}      # (cls_name, out_size) -> 序号
    crops: list = []         # [(zip_path, file_bytes)]

    for rec in records:
        if rec.num_detections == 0 or not rec.detections or not rec.original_path:
            continue
        fp = _url_to_disk(rec.original_path)
        if not fp.exists():
            continue
        img = cv2.imread(str(fp), cv2.IMREAD_UNCHANGED)
        if img is None:
            continue
        # 输出格式跟随原图扩展名
        ext = fp.suffix.lower()
        if ext not in (".bmp", ".png", ".jpg", ".jpeg"):
            ext = ".png"

        for det in rec.detections:
            bbox = det.get("bbox")
            if not bbox:
                continue
            cls_name = det.get("class_name") or f"C{det.get('class_id', 0)}"
            try:
                crop, out_size = _crop_defect_for_classifier(img, bbox)
            except Exception:
                continue
            if crop is None or crop.size == 0:
                continue

            ok, buf = cv2.imencode(ext, crop)
            if not ok:
                continue

            key = (cls_name, out_size)
            idx = counters.get(key, 0)
            counters[key] = idx + 1
            zip_name = f"{cls_name}/{cls_name}_{out_size}_{idx}{ext}"
            crops.append((zip_name, buf.tobytes()))

    if not crops:
        raise HTTPException(400, "推理记录中没有可切割的缺陷")

    mem = io.BytesIO()
    with zipfile.ZipFile(mem, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for name, data in crops:
            zf.writestr(name, data)
    mem.seek(0)

    return StreamingResponse(
        mem,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="project_{project_id}_crops_{len(crops)}.zip"',
            "X-Crop-Count": str(len(crops)),
            # 不放类别名 header（HTTP header 限 latin-1，中文类名会炸）
        },
    )
