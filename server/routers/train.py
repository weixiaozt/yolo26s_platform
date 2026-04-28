# -*- coding: utf-8 -*-
"""
训练管理 API
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.project import Project
from ..models.train_task import TrainTask, TrainEpochLog
from ..schemas.train_task import TrainTaskCreate, TrainTaskOut, EpochLogOut

router = APIRouter(prefix="/api", tags=["训练管理"])


@router.post("/projects/{project_id}/train", response_model=TrainTaskOut, status_code=201)
def create_train_task(
    project_id: int,
    body: TrainTaskCreate,
    db: Session = Depends(get_db),
):
    """创建训练任务（异步执行）"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    # 将项目参数合并到训练配置中
    config = body.config.model_dump()
    config["resize_h"] = project.resize_h
    config["resize_w"] = project.resize_w
    config["crop_size"] = project.crop_size
    config["overlap"] = project.overlap

    task = TrainTask(
        project_id=project_id,
        task_name=body.task_name,
        config=config,
        epochs=config.get("epochs", 200),
        status="pending",
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    # 提交 Celery 异步任务
    from ..tasks.train_task import run_training_pipeline
    celery_result = run_training_pipeline.delay(task.id)
    task.celery_task_id = celery_result.id
    db.commit()
    db.refresh(task)

    return task


@router.get("/projects/{project_id}/train/tasks")
def list_train_tasks(project_id: int, db: Session = Depends(get_db)):
    """获取项目的训练任务列表"""
    tasks = (
        db.query(TrainTask)
        .filter(TrainTask.project_id == project_id)
        .order_by(TrainTask.created_at.desc())
        .all()
    )
    result = []
    for t in tasks:
        d = TrainTaskOut.model_validate(t).model_dump()
        # 从 config 中提取类别数
        if t.config and "class_names" in t.config:
            d["num_classes"] = len(t.config["class_names"])
        result.append(d)
    return result


@router.get("/train/tasks/{task_id}", response_model=TrainTaskOut)
def get_train_task(task_id: int, db: Session = Depends(get_db)):
    """获取训练任务详情"""
    task = db.query(TrainTask).filter(TrainTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@router.get("/train/tasks/{task_id}/epochs", response_model=list[EpochLogOut])
def get_epoch_logs(task_id: int, db: Session = Depends(get_db)):
    """获取训练 Epoch 日志（用于前端绘制训练曲线）"""
    logs = (
        db.query(TrainEpochLog)
        .filter(TrainEpochLog.task_id == task_id)
        .order_by(TrainEpochLog.epoch)
        .all()
    )
    return logs


@router.post("/train/tasks/{task_id}/cancel")
def cancel_train_task(task_id: int, db: Session = Depends(get_db)):
    """取消训练任务"""
    task = db.query(TrainTask).filter(TrainTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    if task.status in ("completed", "failed", "cancelled"):
        raise HTTPException(status_code=400, detail=f"任务已处于终态: {task.status}")

    # 撤销 Celery 任务
    if task.celery_task_id:
        from ..tasks import celery_app
        celery_app.control.revoke(task.celery_task_id, terminate=True)

    task.status = "cancelled"
    db.commit()
    return {"ok": True, "message": "任务已取消"}


@router.delete("/train/tasks/{task_id}", status_code=204)
def delete_train_task(task_id: int, db: Session = Depends(get_db)):
    """删除训练任务"""
    task = db.query(TrainTask).filter(TrainTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 所有非终态都不允许直接删除，必须先取消（取消会真正停掉 Celery 训练循环）
    active_states = ("pending", "preparing", "training", "exporting")
    if task.status in active_states:
        raise HTTPException(status_code=400, detail=f"任务处于活跃状态 ({task.status})，请先取消再删除")

    # 即使是 cancelled / failed，也兜底再 revoke 一次，防止 Celery Worker 残留运行
    if task.celery_task_id:
        try:
            from ..tasks import celery_app
            celery_app.control.revoke(task.celery_task_id, terminate=True)
        except Exception:
            pass

    db.delete(task)
    db.commit()


@router.get("/projects/{project_id}/train/completed-tasks")
def list_completed_tasks(project_id: int, db: Session = Depends(get_db)):
    """列出已完成的训练任务（供继承训练选择）"""
    from ..models.defect_class import DefectClass
    tasks = (
        db.query(TrainTask)
        .filter(TrainTask.project_id == project_id, TrainTask.status == "completed")
        .order_by(TrainTask.finished_at.desc())
        .all()
    )
    # 当前项目类别数
    current_nc = db.query(DefectClass).filter(DefectClass.project_id == project_id).count()

    result = []
    for t in tasks:
        prev_nc = len(t.config.get("class_names", [])) if t.config and "class_names" in t.config else None
        nc_match = (prev_nc == current_nc) if prev_nc is not None else None
        result.append({
            "task_id": t.id,
            "task_name": t.task_name,
            "best_map50": t.best_map50,
            "has_best": bool(t.best_model_path),
            "has_last": bool(t.last_model_path),
            "prev_nc": prev_nc,
            "current_nc": current_nc,
            "nc_match": nc_match,
            "finished_at": t.finished_at.isoformat() if t.finished_at else None,
        })
    return result
