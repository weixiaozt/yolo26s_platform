# yolo26s_platform 升级指南

> 适用：把同事电脑上的旧版本升级到 GitHub `main` 最新版
> 写于：2026-06-23

---

## 升级前必读

### 一定保留（绝对不要删/不要覆盖）

| 内容 | 路径 | 说明 |
|---|---|---|
| 原图与上传数据 | `D:\yolo26s_platform\storage\uploads\` | 所有项目的原始 BMP/PNG |
| 训练产物 | `D:\yolo26s_platform\storage\runs\` | `task_*/runs/train/weights/best.pt` 等 |
| 环境配置 | `D:\yolo26s_platform\.env` | 含数据库密码 / JWT_SECRET，**没有它后端起不来** |
| Python 环境 | `D:\yolo26s_platform\venv\` | 千万别动，重装一次要装 GB 级依赖 |
| 前端依赖 | `D:\yolo26s_platform\web\node_modules\` | 同上 |
| 数据库 | MySQL `yolo_seg` 库 | 在 MySQL 服务里，不在文件夹下 |
| 用户自定义 | `mask2png.py`（如果有） | 用户自己的工具 |

### 不需要做

- **不需要手动跑 SQL** — 启动后端时自动执行 `server/database.py` 里的 ALTER TABLE（IF NOT EXISTS 形式）
- **不需要 pip install / npm install** — 本次升级没有新增依赖
- **不需要重训模型** — 模型权重格式没变

---

## 情况 A：同事电脑是 git clone 的（推荐路径）

### 怎么判断是这种情况

打开 cmd，执行：
```cmd
cd /d D:\yolo26s_platform
git status
```

如果有输出（显示分支名 / 文件变更），就是 git 仓库 → **走情况 A**
如果报 `fatal: not a git repository`，就是 zip 拷的 → **走情况 B**

### A 详细步骤

#### A.1 关掉后端服务

打开任务管理器 → 找到这几个 python 进程并结束：
- uvicorn（命令行含 `server.main:app`）
- celery（命令行含 `celery -A server.tasks`）
- vite（如果在跑 `npm run dev`，关掉 cmd 窗口即可）

或者 cmd 一键全杀（**警告**：会杀掉所有 python 进程，确认没在跑其他 Python 程序）：
```cmd
taskkill /F /IM python.exe
```

#### A.2 检查本地是否有未提交的改动

```cmd
cd /d D:\yolo26s_platform
git status
```

- 如果显示 `nothing to commit, working tree clean` → 跳过下面 stash，直接 git pull
- 如果有改动（同事自己改了代码？）：
  ```cmd
  git stash push -m "本地改动暂存-升级前"
  ```

#### A.3 拉取最新代码

```cmd
git fetch origin main
git log --oneline HEAD..origin/main      :: 看会拉哪些 commit
git pull --ff-only origin main           :: 快进合并（不会产生 merge commit）
```

如果 pull 报错 `Not possible to fast-forward, aborting`，说明本地有提交但跟远端冲突。简单粗暴恢复（**会丢本地提交**）：
```cmd
git fetch origin
git reset --hard origin/main
```

#### A.4 查看升级到了哪个版本

```cmd
git log --oneline -1
```

记一下这个 commit hash，方便出问题时回退。

#### A.5 启动后端（数据库会自动迁移）

打开 cmd（管理员）：
```cmd
set YOLO_AUTOINSTALL=False
D:\yolo26s_platform\venv\Scripts\python.exe -m uvicorn server.main:app --host 0.0.0.0 --port 8000
```

启动日志里会看到 `[迁移] 已添加 xxx` 字样，等出现：
```
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000
```
才算 OK。

#### A.6 启动 Celery Worker（另一个 cmd 窗口）

```cmd
set YOLO_AUTOINSTALL=False
D:\yolo26s_platform\venv\Scripts\python.exe -m celery -A server.tasks worker --loglevel=info --pool=solo
```

等出现 `[tasks] . tasks.run_training_pipeline`。

#### A.7 启动前端（第三个 cmd 窗口）

```cmd
cd /d D:\yolo26s_platform\web
npm run dev
```

等出现 `VITE v* ready in ** ms ➜ Local: http://localhost:5174/`。

#### A.8 验证

浏览器打开 http://localhost:5174 ，登录 `admin / admin123`：
- 项目列表能正常显示
- 进任意 seg 项目 → 在线推断 → 设备下拉能看到 CPU + CUDA + OV CPU/GPU.0/GPU.1
- 模型转换页能看到带"内嵌 NMS"开关
- 标注页画笔尺寸旁边有数字输入框

如果有缓存问题，浏览器 Ctrl+F5 强刷。

#### A.9 如果之前 stash 了改动

```cmd
git stash pop
```
有冲突手动解决。

---

## 情况 B：同事电脑是 zip 拷的，没 .git 目录

直接解压本次提供的**更新包**到 `D:\yolo26s_platform\`，覆盖所有同名文件。

### B 详细步骤

#### B.1 关掉后端服务

同 A.1（taskkill 或任务管理器）。

#### B.2 解压更新包

把 `yolo26s_update_<日期>.zip` 拷到同事电脑，**直接解压到 `D:\yolo26s_platform\`**：
- 解压工具问"是否覆盖"全部选**是**
- 解压包里**不包含** `venv/` / `node_modules/` / `storage/` / `.env` / `*.pt` / `*.zip`，所以你的环境和数据**不会被动**

#### B.3 备份 .env（保险起见）

万一你之前不小心覆盖过 `.env`：
```cmd
cd /d D:\yolo26s_platform
type .env       :: 看一眼内容，确认含 DB_PASSWORD 等关键字段
```

#### B.4 启动后端 / Celery / 前端

同 A.5 / A.6 / A.7。

#### B.5 验证

同 A.8。

#### B.6（建议）转成 git 仓库，方便以后升级

未来每次升级你都得我重新打包发给你太麻烦，建议这一次顺手把同事电脑转成 git 仓库，以后他可以自己 `git pull`：

```cmd
cd /d D:\yolo26s_platform
git init
git remote add origin https://github.com/weixiaozt/yolo26s_platform.git
git fetch
git checkout -ft origin/main
```

⚠️ `git checkout -ft` 会**强制覆盖**所有 git tracked 的文件，但不会动 `.env` / `storage/` / `venv/` / `node_modules/`（这些都在 `.gitignore` 里）。

以后升级就走情况 A 的流程。

---

## 故障排查

### Q1: uvicorn 启动报 `1146 (42S02): Table 'yolo_seg.xxx' doesn't exist`
你这台机器的 `yolo_seg` 数据库还没初始化，或者库名不对。先确认 MySQL 服务在跑：
```cmd
net start mysql80
```
然后看 `D:\yolo26s_platform\.env` 里 `DATABASE_URL` 是不是 `mysql+pymysql://root:123456@localhost:3306/yolo_seg`。
如果是新装的 MySQL，需要先建库：
```cmd
mysql -u root -p123456 -e "CREATE DATABASE yolo_seg DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
```
建好库再启动 uvicorn，所有表会自动 `Base.metadata.create_all()` 创建。

### Q2: uvicorn 启动报 `requirement ['onnxruntime-gpu'] not found, attempting AutoUpdate...` 卡住
Ultralytics 在自动装包但下载卡死。环境变量没生效：
```cmd
set YOLO_AUTOINSTALL=False
```
必须在**启动 uvicorn 前的同一个 cmd 窗口**里 set，新窗口要重新 set。永久生效可以用 `setx YOLO_AUTOINSTALL False`（重启 cmd 生效）。

### Q3: celery 报 `KeyError: 'task_type'` 或类似字段错误
uvicorn 还没把数据库迁移完，celery 就启动了。**先把 uvicorn 完整启动**（看到 `Application startup complete`），再起 celery。

### Q4: 前端白屏 / 看不到新功能
浏览器缓存。`Ctrl+F5` 强刷一次。还不行就清浏览器缓存（F12 → Application → Storage → Clear site data）。

### Q5: 推断页设备下拉只有 CPU，看不到 GPU
1. 看 cuda 是否能用：
   ```cmd
   D:\yolo26s_platform\venv\Scripts\python.exe -c "import torch; print(torch.cuda.is_available(), torch.cuda.device_count())"
   ```
   如果 `False 0` → 显卡驱动 / cuda toolkit 有问题
2. 重启 uvicorn 试一次（有个偶发 bug：uvicorn 进程偶尔会拿不到 cuda 上下文，重启即恢复）

### Q6: 同事改过的本地代码丢了
A 路径：`git stash list` 看一下，有就 `git stash pop`
B 路径：解压前没备份就丢了，下次记得先 `git init && git commit -am 'baseline'` 留个底

### Q7: 想回退到升级前版本
A 路径：`git log --oneline` 找到升级前那个 hash，`git reset --hard <hash>`
B 路径：用你升级前的备份 zip 重新解压（建议每次升级前用 7z 把整个目录打个备份）

---

## 升级日志（HEAD `f606bba`，2026-06-23）

自上次给同事打包（可能是 5 月初）以来的主要变化：

### 新功能
- 标注器画笔尺寸加输入框，可直接输数字（之前只能拖滑块）
- 标注器涂抹工具加 Shift 追加模式（大缺口分多笔涂会自动合并）
- 标注器 scanContour 改 Moore-Neighbor 边界追踪（修 U/S/L/C 形涂抹被填实 bug）
- 模型导出支持"内嵌 NMS"选项（OV / ONNX 末端嵌入 NMS 节点，部署端不用自己写）
- 设备下拉列出所有 OV 设备（CPU / iGPU / dGPU）
- YOLO26-seg + OV 已实测可用，TrainConfig 模型下拉去掉过时警告

### 性能 / 磁盘
- 训练数据集**改硬链接**，新任务的 dataset/ 几乎不占空间（之前每个 task 复制几百 MB）
- `tools/cleanup_storage.py` 加 dataset/ 清理项，可一键释放历史欠账（本机一次释放 37GB）

### Bug 修复
- 切割小图坐标系修复（之前用原图 4K 坐标切缩放后 2560 坐标 bbox，位置错位）
- OV 下载 zip 缓存命名冲突 + Windows 目录 mtime 失效
- 推理设备下拉缺失 OV 设备
- crop-defects 输出 38 维含义文档化（见 [docs/yolo26_vs_yolo11_deployment.md](docs/yolo26_vs_yolo11_deployment.md)）

### 文档
- `docs/openvino_nms_export.md` — OV 内嵌 NMS 部署说明（给同事看的）
- `docs/yolo26_vs_yolo11_deployment.md` — YOLO26 vs 11 选型 + 避坑
- `docs/crop_defects_logic.md` — 切割小图功能内部逻辑
- `docs/upgrade_guide.md` — 就是本文档

---

## 数据库自动迁移项（这次升级会跑的 ALTER TABLE）

后端启动时按需执行（已有的会跳过）：

| 表 | 字段 | 用途 |
|---|---|---|
| `exported_models` | `nms` TINYINT | 标记导出是否带内嵌 NMS |
| `projects` | `task_type` ENUM 扩展 obb | 第四种任务类型 |
| `projects` | `last_train_config` JSON | 项目级训练参数缓存 |
| `images` | `class_id` INT + FK | cls 项目的图级分类标签 |
| `train_epoch_logs` | `top1_acc` / `top5_acc` | cls 训练指标 |
| `train_tasks` | `best_fitness` | 真实 best.pt 指标 |

不需要手动跑 SQL，启动 uvicorn 后看日志里 `[迁移] 已添加 xxx` 出现即可。

---

## TL;DR

- **同事电脑有 .git**：A 路径，`git pull` + 重启服务
- **同事电脑没 .git**：B 路径，解压更新包覆盖 + 重启服务（建议顺手转成 git 仓库）
- 数据库自动迁移，无需手动 SQL
- 不需要 pip / npm install
- 保留 `storage/` / `.env` / `venv/` / `node_modules/`
- 浏览器 Ctrl+F5 刷新前端缓存
