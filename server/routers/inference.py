# -*- coding: utf-8 -*-
"""推断服务 API（支持 .pt / ONNX / OpenVINO / TensorRT）"""

import sys
import uuid
import base64
from pathlib import Path

import cv2
import numpy as np
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..config import settings
from ..models.train_task import TrainTask
from ..models.inference_result import InferenceResult
from ..models.exported_model import ExportedModel
from ..models.defect_class import DefectClass

_root = str(Path(__file__).parent.parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

router = APIRouter(prefix="/api/inference", tags=["推断服务"])
_model_cache: dict = {}


def _get_model(model_path: str):
    """加载模型（缓存）。Ultralytics 自动识别格式"""
    if model_path in _model_cache:
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
        del _model_cache[next(iter(_model_cache))]
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
    """单张推断 + 持久化"""
    # 确定模型路径
    mp = model_path
    if not mp and task_id > 0:
        task = db.query(TrainTask).filter(TrainTask.id == task_id).first()
        if task and task.best_model_path:
            mp = task.best_model_path
    if not mp or not Path(mp).exists():
        raise HTTPException(status_code=404, detail="模型文件不存在")

    # 推断配置（从训练任务获取）
    crop_size, overlap = 640, 0.2
    use_morphology, dilate_kernel, erode_kernel = False, 3, 3
    if task_id > 0:
        task = db.query(TrainTask).filter(TrainTask.id == task_id).first()
        if task and task.config:
            crop_size = task.config.get("crop_size", 640)
            overlap = task.config.get("overlap", 0.2)
            use_morphology = task.config.get("use_morphology", False)
            dilate_kernel = task.config.get("dilate_kernel", 3)
            erode_kernel = task.config.get("erode_kernel", 3)
        if not project_id and task:
            project_id = task.project_id
    print(f"[推断] task_id={task_id}, use_morphology={use_morphology}, config_keys={list(task.config.keys()) if task and task.config else None}")

    # 读取图像（保持原始格式，灰度转换由 inference 内部处理）
    content = await file.read()
    img_array = cv2.imdecode(np.frombuffer(content, np.uint8), cv2.IMREAD_UNCHANGED)
    if img_array is None:
        raise HTTPException(status_code=400, detail="无法读取图像")

    # 加载模型并推断
    model = _get_model(mp)
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

    # 加载类别名称映射
    class_names = {}
    if project_id > 0:
        dcs = db.query(DefectClass).filter(DefectClass.project_id == project_id).all()
        class_names = {dc.class_index: dc.name for dc in dcs}

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
        filename=file.filename or "unknown", device=device,
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
        "num_detections": record.num_detections,
        "inference_time": record.inference_time,
        "detections": detections,
        "filename": record.filename,
        "original_url": record.original_path,
        "overlay_url": record.overlay_path,
        "overlay_morph_url": f"{url_pfx}/{rid}_overlay_morph.png" if result.get("overlay_morph") is not None else None,
        "mask_url": record.mask_path,
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
            if "class_name" not in d:
                cid = d.get("class_id", 0)
                d["class_name"] = names.get(cid, f"C{cid}")
        return dets

    return {"total": total, "page": page, "page_size": page_size, "items": [
        {"id": r.id, "filename": r.filename, "num_detections": r.num_detections,
         "inference_time": r.inference_time, "device": r.device,
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
