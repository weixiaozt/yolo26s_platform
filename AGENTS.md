# AGENTS.md — yolo26s_platform

工业缺陷检测全栈平台（硅晶圆/方锭/光伏）。Vue 3 前端 + FastAPI 后端 + Celery 训练队列 + MySQL/Redis + Ultralytics YOLO。

---

## 启动

后端 + Celery（必须**两个**进程都开）：
```bash
# 在 D:\yolo26s_platform 目录
D:/yolo26s_platform/venv/Scripts/python.exe -m uvicorn server.main:app --host 0.0.0.0 --port 8000
D:/yolo26s_platform/venv/Scripts/python.exe -m celery -A server.tasks worker --loglevel=info --pool=solo
```

前端：
```bash
cd web && npm run dev   # 默认 http://localhost:5174
```

环境变量（避免 ultralytics 联网装包卡住）：
```
YOLO_AUTOINSTALL=False
```

默认账号：`admin / admin123`。

---

## 改了代码必须重启的范围

| 改动 | 重启 |
|---|---|
| `server/routers/*` | uvicorn |
| `server/services/*`, `server/models/*`, `server/schemas/*` | uvicorn |
| `server/tasks/*`, `core/*` | celery worker（uvicorn 也建议） |
| `web/src/*` | 不需要，vite hot reload 自动 |

uvicorn 没开 `--reload`，必须手动 kill PID + 重启。

---

## 4 种任务类型

`projects.task_type` 决定整个流水线行为：

| type | 含义 | 训练数据集 | 模型默认 | 切片 |
|---|---|---|---|---|
| `seg` | 实例分割 | YOLO polygon txt | yolo26s-seg.pt | 大图 → resize → 滑窗 crop_size² |
| `det` | 目标检测 | YOLO bbox txt | yolo26s.pt | 同 seg |
| `cls` | 图像分类 | ImageFolder `dataset/<class>/` | yolo11s-cls.pt | **不切片**，整图 letterbox 到 imgsz |
| `obb` | 旋转目标检测 | YOLO 4 角点 txt（8 归一化坐标） | yolo11s-obb.pt | 同 seg |

cls 标签存 `images.class_id`（图级），其他 task 标签存 `annotations.polygon`（实例级）。

---

## cls 任务的几个坑（已修复，留作 reminder）

1. **imgsz 必须 224**：YOLO11-cls 在 ImageNet 224 预训练。`core/train.py` 已经强制 `if imgsz != 224: imgsz = 224`，并把 degrees/flipud/mosaic/copy_paste/mixup 全置 0。项目级 crop_size 对 cls 无意义。

2. **类别名映射用 model.names，不要用 DB class_index**：cls 训练用 ImageFolder 模式，类别 index 是子目录名字典序（如 Broken=0, Crack=1, OK=2），与 DB 创建顺序不一致。`_resolve_class_names` 优先 model.names，DB 仅兜底。

3. **EasyLabel BMP 多是 128×128 单通道灰度**：cv2.imread 默认会扩成三通道，但训练/推理预处理要保持一致。

---

## 关键文件位置

```
core/
  train.py             — Ultralytics 训练入口，task_type 分支 + cancel_check 回调
  inference.py         — 滑窗推理（seg/det）
  preprocess.py        — Resize + 形态学（B=原图 G=膨胀 R=腐蚀 三通道）
  sliding_window.py    — 滑窗切割

server/
  main.py              — FastAPI 入口；monkey-patch starlette MultiPartParser.max_files=100000
  database.py          — Engine + 自动 ALTER TABLE 迁移列表（每次新加字段往这里追加）
  config.py            — settings.upload_path / runs_path / DATABASE_URL
  models/              — SQLAlchemy ORM
  schemas/             — pydantic
  routers/             — FastAPI 路由
  services/
    dataset_service.py — 4 种 task_type 的数据集准备（prepare_*_dataset）
    project_package.py — 项目导出/导入 zip
  tasks/train_task.py  — Celery 训练任务，内含 cancel_check 注入

web/src/views/
  ProjectList.vue      — 项目管理（按 task_type 分组）
  ProjectDetail.vue    — 项目详情 + 编辑弹窗
  Annotator.vue        — 通用标注器（seg/det/obb 用）
  ClsAnnotator.vue     — cls 6×6 网格批量打标
  AnnotationConvert.vue — seg ⇆ det/obb 标注转换
  ImportProject.vue    — 多种导入入口（VOC/cls 文件夹）
  TrainConfig.vue      — 训练配置（参数缓存 + 继承训练自动加载）
  TrainMonitor.vue     — 训练监控（epoch 曲线 + 完整参数展示）
  InferenceView.vue    — 在线推断（队列 + 推理训练图 + 网格 + 切割小图）

tools/
  cleanup_storage.py   — 存储瘦身（推理缓存 + epoch checkpoints + 预处理产物）
  verify_cls.py        — cls 模型全量验证 + 混淆矩阵
  test_cls_pipeline.py — cls 端到端回归测试
```

---

## 推理 endpoint 路径速查

```
POST /api/inference/run                  上传图推理（multipart）
POST /api/inference/run-by-image-id      按 image_id 推理（不上传，跳本地读）
GET  /api/inference/project-images       项目图片抽样列表（推理训练图用）
POST /api/inference/crop-defects         seg 项目缺陷小图打 zip 下载
GET  /api/inference/models               模型下拉（含 cancelled 任务，文件存在性检查）
GET  /api/inference/devices              GPU 列表
GET  /api/inference/history              历史记录
PUT  /api/projects/{id}/train-config-cache    保存项目级训练参数缓存
GET  /api/projects/{id}/images/class-stats    cls 项目类别分布（项目全量）
PUT  /api/projects/{id}/images/batch-class    cls 批量打分类标签
```

---

## 训练任务可继承的状态

`completed` + `cancelled` 都允许（cancelled 任务硬盘上仍有 best.pt/last.pt，ultralytics 实时写盘）。
- 推断模型下拉、继承训练下拉两处都做了文件存在性检查
- cancelled 任务 label 加 `[取消@epoch N/M]` 标识
- best vs last 推荐：completed → best；cancelled 进度 < 30% → last（best 没收敛接着学）；≥ 30% → best

---

## 取消训练机制

`core/train.py` 注册三个 ultralytics 回调：
- `on_train_epoch_start`、`on_fit_epoch_end`：每 epoch 边界查 db
- `on_train_batch_end`：每 20 batch 查一次（throttle）

检测到 `task.status == 'cancelled'` 或任务被删 → `trainer.stop = True`，YOLO 在 epoch 边界优雅退出。最坏 ~20 秒生效。

`server/routers/train.py` delete 接口拒绝删 `pending/preparing/training/exporting`，对 cancelled/failed 兜底 revoke。

---

## 训练内存 / Workers / 跨版本部署坑（2026-07-21）

1. **不要再强制 `cache="ram"`**：4050 张 640×640 三通道切片解码后约占 4.6 GiB。RTX 3060 6GB + 16GB RAM 机器曾在 CUDA OOM 自动重建 DataLoader 时耗尽系统内存，最后只显示 OpenCV `Failed to allocate 1228800 bytes`。`core/train.py` 现固定 `cache=False`；只影响读盘速度，不影响精度。
2. **看完整 traceback 的第一处 OOM**：最终的 OpenCV `Insufficient memory` 可能只是二次异常，真正原因常是前面的 `torch.OutOfMemoryError: CUDA out of memory`。资源类失败由 `server/tasks/train_task.py` 转成中文参数建议，同时保留技术堆栈。
3. **Workers 是给高配机提速的，不要全局禁用**：2026-07-04 提交 `0f25d3f` 把固定 `workers=0` 改成可配置；4070 Ti 机器建议先试 4，Windows 异常时回到 0。RTX 3060 6GB / 16GB RAM 建议 0～2。实测 `batch=16, workers=2` 可跑；`batch=64, workers=6` 会爆 6GB 显存并放大内存峰值。
4. **Celery 是常驻进程**：训练成功、失败、取消后都必须 `gc.collect()` + `torch.cuda.empty_cache()` + `torch.cuda.ipc_collect()`；已在任务 `finally` 统一执行。改了 `core/*` 或 `server/tasks/*` 后必须重启 Celery，运行中的旧 worker 不会热加载。
5. **`unexpected keyword argument 'workers'` 是混版，不是模型缺失**：说明新版 `server/tasks/train_task.py` 配了旧版 `core/train.py`，或 Celery 仍缓存旧模块。完整同步 `server/` + `core/`，确认 `inspect.signature(core.train.run_train)` 含 `workers`，再重启 uvicorn/Celery。复制 `.pt` 不能解决参数签名错误。
6. **任务管理器里的 Python 成对出现属正常**：uv 管理的 venv 启动器会再拉起实际 Python；通常一组是 uvicorn，一组是 Celery。用进程命令行区分，不要按名称误杀同机其它 Python 项目。

---

## 工作约定

1. **不要每次自动 `git push`**。只在用户明确说"提交/合并/push"时推。
2. **commit 风格**：`feat/fix/tune/tool: 中文描述`，message 带 `Co-Authored-By: Codex` 行。
3. **mask2png.py 是用户的 GUI 工具**，git status untracked 不要碰。
4. **`*.pt` 已加 .gitignore**，模型权重不入库。
5. **改 db 字段**：往 `server/database.py` migrations list 末尾追加 ALTER TABLE 语句（IF NOT EXISTS 形式，重启自动执行）。
6. **cancel 任务后还想用其 best.pt**：直接去 `D:\yolo26s_platform\storage\runs\task_<N>\runs\train\weights\best.pt`，前端在线推断也能选到。

---

## 数据库

```
mysql+pymysql://root:123456@localhost:3306/yolo_seg
```

不支持 `NULLS LAST`，排序 nullable 字段用 `func.coalesce(col_a, col_b)`。

---

## 用户硬件 / 环境

- GPU: RTX 3060 6GB 移动版（同事相同）
- OS: Windows 11 Pro for Workstations
- shell: git-bash（Bash 工具默认）—— Linux 风格命令
