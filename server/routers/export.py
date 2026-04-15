# -*- coding: utf-8 -*-
"""
模型转换/导出 API
"""

import sys
import threading
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db, SessionLocal
from ..config import settings
from ..models.train_task import TrainTask
from ..models.exported_model import ExportedModel

_root = str(Path(__file__).parent.parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

router = APIRouter(prefix="/api/export", tags=["模型导出"])


class ExportRequest(BaseModel):
    task_id: int
    source_type: str = Field(default="best")           # best / last
    export_format: str = Field(default="onnx")          # onnx / openvino / tensorrt
    imgsz: int = Field(default=640, ge=320, le=1280)
    half: bool = Field(default=False)                    # FP16
    int8: bool = Field(default=False)                    # INT8 量化（仅 OpenVINO）


@router.get("/list")
def list_exports(task_id: int = 0, project_id: int = 0, db: Session = Depends(get_db)):
    """列出已导出的模型（按项目或任务过滤）"""
    q = db.query(ExportedModel)
    if task_id > 0:
        q = q.filter(ExportedModel.task_id == task_id)
    elif project_id > 0:
        task_ids = [t.id for t in db.query(TrainTask.id).filter(TrainTask.project_id == project_id).all()]
        q = q.filter(ExportedModel.task_id.in_(task_ids))
    items = q.order_by(ExportedModel.created_at.desc()).all()
    return [
        {
            "id": e.id,
            "task_id": e.task_id,
            "source_type": e.source_type,
            "export_format": e.export_format,
            "export_path": e.export_path,
            "file_size_mb": round(e.file_size_mb or 0, 2),
            "imgsz": e.imgsz,
            "half": e.half == 1,
            "int8": e.half == 2,
            "precision": {0: "FP32", 1: "FP16", 2: "INT8"}.get(e.half, "FP32"),
            "status": e.status,
            "error_message": e.error_message,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in items
    ]


@router.get("/tasks")
def list_exportable_tasks(project_id: int = 0, db: Session = Depends(get_db)):
    """列出可导出的训练任务（按项目过滤）"""
    q = db.query(TrainTask).filter(TrainTask.status == "completed")
    if project_id > 0:
        q = q.filter(TrainTask.project_id == project_id)
    tasks = q.order_by(TrainTask.finished_at.desc()).all()
    result = []
    for t in tasks:
        models = []
        if t.best_model_path:
            models.append({"type": "best", "path": t.best_model_path})
        if t.last_model_path:
            models.append({"type": "last", "path": t.last_model_path})
        if models:
            result.append({
                "task_id": t.id,
                "task_name": t.task_name,
                "models": models,
                "finished_at": t.finished_at.isoformat() if t.finished_at else None,
            })
    return result


@router.post("/run")
def run_export(req: ExportRequest, db: Session = Depends(get_db)):
    """提交模型导出任务（后台线程执行）"""
    task = db.query(TrainTask).filter(TrainTask.id == req.task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="训练任务不存在")

    src_path = task.best_model_path if req.source_type == "best" else task.last_model_path
    if not src_path or not Path(src_path).exists():
        raise HTTPException(status_code=404, detail="模型文件不存在")

    # 检查是否已有相同导出
    existing = db.query(ExportedModel).filter(
        ExportedModel.task_id == req.task_id,
        ExportedModel.source_type == req.source_type,
        ExportedModel.export_format == req.export_format,
        ExportedModel.imgsz == req.imgsz,
        ExportedModel.status == "completed",
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="该格式已导出，无需重复导出")

    # 创建记录（half: 0=FP32, 1=FP16, 2=INT8）
    record = ExportedModel(
        task_id=req.task_id,
        source_path=src_path,
        source_type=req.source_type,
        export_format=req.export_format,
        imgsz=req.imgsz,
        half=2 if req.int8 else (1 if req.half else 0),
        status="exporting",
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    # 后台线程执行导出
    export_id = record.id
    # INT8 量化需要数据集路径
    dataset_path = None
    if req.int8:
        task = db.query(TrainTask).filter(TrainTask.id == req.task_id).first()
        if task and task.output_dir:
            dataset_path = str(Path(task.output_dir) / "dataset")
    threading.Thread(
        target=_do_export,
        args=(export_id, src_path, req.export_format, req.imgsz, req.half, req.int8, dataset_path),
        daemon=True,
    ).start()

    return {"id": export_id, "status": "exporting", "message": "导出任务已启动"}


def _do_export(export_id: int, src_path: str, fmt: str, imgsz: int, half: bool, int8: bool = False, dataset_path: str = None):
    """后台执行导出"""
    db = SessionLocal()
    try:
        record = db.query(ExportedModel).filter(ExportedModel.id == export_id).first()
        if not record:
            return

        from core.export import run_export
        output_dir = str(Path(src_path).parent / "exports")
        result = run_export(
            model_path=src_path,
            output_dir=output_dir,
            export_format=fmt,
            imgsz=imgsz,
            half=half,
            int8=int8,
            dataset_path=dataset_path,
        )

        if result.get("error"):
            record.status = "failed"
            record.error_message = result["error"]
        else:
            record.status = "completed"
            record.export_path = result.get("export_path")
            record.onnx_path = result.get("onnx_path")
            # 计算文件大小
            ep = result.get("export_path")
            if ep:
                p = Path(ep)
                if p.is_file():
                    record.file_size_mb = p.stat().st_size / 1024 / 1024
                elif p.is_dir():
                    total = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
                    record.file_size_mb = total / 1024 / 1024
        db.commit()
    except Exception as e:
        record = db.query(ExportedModel).filter(ExportedModel.id == export_id).first()
        if record:
            record.status = "failed"
            record.error_message = str(e)
            db.commit()
    finally:
        db.close()


@router.delete("/{export_id}")
def delete_export(export_id: int, db: Session = Depends(get_db)):
    """删除导出记录"""
    record = db.query(ExportedModel).filter(ExportedModel.id == export_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")
    db.delete(record)
    db.commit()
    return {"ok": True}


# ============================================================
# 模型下载
# ============================================================
from fastapi.responses import FileResponse
import shutil
import tempfile


@router.get("/download/pt/{task_id}/{model_type}")
def download_pt_model(task_id: int, model_type: str, db: Session = Depends(get_db)):
    """下载原始 .pt 模型"""
    task = db.query(TrainTask).filter(TrainTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    model_path = task.best_model_path if model_type == "best" else task.last_model_path
    if not model_path or not Path(model_path).exists():
        raise HTTPException(status_code=404, detail="模型文件不存在")

    filename = f"task{task_id}_{model_type}.pt"
    return FileResponse(model_path, media_type="application/octet-stream", filename=filename)


@router.get("/download/exported/{export_id}")
def download_exported_model(export_id: int, db: Session = Depends(get_db)):
    """下载导出的模型（单文件直接下载，目录打 zip 下载）"""
    record = db.query(ExportedModel).filter(ExportedModel.id == export_id).first()
    if not record or not record.export_path:
        raise HTTPException(status_code=404, detail="记录不存在")

    ep = Path(record.export_path)
    if not ep.exists():
        raise HTTPException(status_code=404, detail="导出文件不存在")

    task = db.query(TrainTask).filter(TrainTask.id == record.task_id).first()
    tname = f"task{record.task_id}"

    if ep.is_file():
        # 单文件：ONNX / TensorRT
        filename = f"{tname}_{record.source_type}.{record.export_format}{ep.suffix}"
        return FileResponse(str(ep), media_type="application/octet-stream", filename=filename)
    elif ep.is_dir():
        # 目录：OpenVINO → 打 zip
        zip_name = f"{tname}_{record.source_type}_{record.export_format}"
        tmp_dir = Path(tempfile.gettempdir()) / "model_downloads"
        tmp_dir.mkdir(exist_ok=True)
        zip_path = tmp_dir / f"{zip_name}.zip"

        # 如果 zip 已存在且较新，直接用缓存
        if not zip_path.exists() or zip_path.stat().st_mtime < ep.stat().st_mtime:
            shutil.make_archive(str(zip_path.with_suffix("")), "zip", str(ep.parent), ep.name)

        return FileResponse(str(zip_path), media_type="application/zip", filename=f"{zip_name}.zip")
    else:
        raise HTTPException(status_code=404, detail="导出路径无效")
