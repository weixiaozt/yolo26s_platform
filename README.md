# YOLO26s-Seg 工业缺陷检测全栈平台

> 一站式工业视觉缺陷检测平台 — 标注、训练、推断、模型导出全流程闭环。
> 面向硅晶圆 / 方锭 / 光伏组件等工业场景，支持 4 种任务类型一键切换。

![Vue 3](https://img.shields.io/badge/Vue-3-42b883) ![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688) ![YOLO](https://img.shields.io/badge/YOLO-26s%20%2F%2011-yellow) ![Python](https://img.shields.io/badge/Python-3.11-blue) ![License](https://img.shields.io/badge/License-Internal-lightgrey)

---

## ✨ 平台特性

### 🎯 4 种任务类型，按需选择

| 任务 | 适用场景 | 默认模型 | 标注方式 |
|------|---------|---------|---------|
| **实例分割（seg）** | 缺陷区域不规则，需要像素级轮廓 | yolo26s-seg | 多边形 |
| **目标检测（det）** | 缺陷为矩形包围框即可定位 | yolo26s | 矩形 |
| **图像分类（cls）** | 整图判断良/不良或多分类 | yolo11s-cls | 整图打标签 |
| **旋转检测（obb）** | 缺陷有方向（如裂纹角度） | yolo11s-obb | 4 角点旋转矩形 |

### 🛠 核心能力

- **可视化标注器** — 多边形 / 矩形 / 旋转矩形 / 复制粘贴 / 顶点编辑 / 整体旋转手柄 / 快捷键
- **批量分类标注** — 6×6 网格一键打标，类别筛选 + 项目级统计
- **大图滑窗训练** — 自动 resize + 滑窗 crop，适配 4096×4096 高分辨率工业图
- **形态学三通道预处理** — 原图 + 膨胀 + 腐蚀拼合（B/G/R），强化边缘特征
- **训练实时监控** — Loss 曲线、mAP50、参数全量展示、可中途取消（最快 20 秒生效）
- **训练参数缓存** — 按项目记忆上次配置，继承训练自动加载历史 config
- **在线推断** — 训练图抽样 / 网格视图 / 缺陷小图打 zip / cancelled 任务也能推断
- **模型导出** — ONNX / OpenVINO / TensorRT 三种格式，FP32 / FP16 / INT8 精度可选
- **标注互转** — seg ⇄ det ⇄ obb 三向转换，原标注无损保留

---

## 📸 软件界面

### 项目管理 — 按任务类型分组

支持实例分割、图像分类、旋转检测、目标检测 4 种项目类型，分组展示。

![项目管理](docs/screenshots/01-project-list.png)

### 项目详情 — 图片库 + 标注状态

进入项目后查看图像总数、标注进度、缺陷统计，按状态（未标注 / 标注中 / 有缺陷 / OK）筛选。

![项目详情](docs/screenshots/02-project-detail.png)

### 训练监控 — Loss 曲线 + mAP + 完整参数

实时显示训练进度、最佳 mAP50、每个 epoch 的 Box/Seg/Cls/DFL Loss 曲线。"训练参数"卡片可一键复制 JSON，下次直接套用。

![训练监控](docs/screenshots/03-train-monitor.png)

### 在线推断 — 大图滑窗检测

支持原图 / Mask / 同时显示三种视图，列表与网格切换。可一键"推理训练图"批量生成展示集，也可"切割小图"导出缺陷裁切 zip 用于二级分类训练。

![在线推断](docs/screenshots/04-inference.png)

### 模型转换 — 一键导出 ONNX / OpenVINO / TensorRT

完整列出所有训练任务（含已取消的，因为 best.pt 仍在硬盘上）。分类项目自动锁定 224×224，避免误改。

![模型转换](docs/screenshots/05-model-export.png)

---

## 🚀 快速开始

```bash
# 克隆仓库
git clone <repo-url> D:\yolo26s_platform
cd D:\yolo26s_platform

# 创建虚拟环境
python -m venv venv
venv\Scripts\activate

# 安装依赖
pip install -r server/requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
pip install openvino onnx onnxslim onnxruntime -i https://pypi.tuna.tsinghua.edu.cn/simple

# 配置环境变量
copy .env.example .env
# 编辑 .env 修改数据库密码 / JWT 密钥

# 准备数据库（确保 MySQL + Redis 已启动）
mysql -u root -p123456 -e "CREATE DATABASE IF NOT EXISTS yolo_seg CHARACTER SET utf8mb4;"

# 启动（双击 start_all.bat 或分别启动 3 个服务）
start_all.bat
```

浏览器打开 `http://localhost:5174`，默认账号 `admin / admin123`。

> 完整部署教程见 [详细部署指南](#-详细部署指南)。

---

## 🏗 技术栈

| 层 | 选型 |
|----|------|
| 前端 | Vue 3 + TypeScript + Vite + Element Plus + Fabric.js |
| 后端 | FastAPI + SQLAlchemy + Pydantic |
| 训练 | Ultralytics YOLO（YOLO26s 实例分割 / YOLO11 OBB 旋转） |
| 任务队列 | Celery + Redis（Windows pool=solo 模式） |
| 数据库 | MySQL 8.0（utf8mb4） |
| 推断加速 | ONNX Runtime / OpenVINO / TensorRT |

---

## 📂 项目结构

```
D:\yolo26s_platform\
├── core/                    ← YOLO 训练 / 推断 / 滑窗 / 形态学预处理
│   ├── train.py             ← 训练入口（4 种 task_type 分支）
│   ├── inference.py         ← 滑窗推理
│   ├── preprocess.py        ← B 原图 + G 膨胀 + R 腐蚀
│   └── sliding_window.py
├── server/                  ← FastAPI 后端
│   ├── routers/             ← REST API 路由
│   ├── services/
│   │   ├── dataset_service.py    ← 4 种 task 数据集准备
│   │   ├── project_package.py    ← 项目导出 / 导入
│   │   └── project_convert.py    ← 标注 seg ⇄ det ⇄ obb 互转
│   ├── tasks/train_task.py  ← Celery 训练任务
│   └── database.py          ← 自动迁移 ALTER TABLE
├── web/src/
│   ├── views/
│   │   ├── ProjectList.vue       ← 项目管理（按 task_type 分组）
│   │   ├── Annotator.vue         ← 通用标注器（seg/det/obb）
│   │   ├── ClsAnnotator.vue      ← 6×6 网格批量打标
│   │   ├── TrainMonitor.vue      ← 训练监控 + 参数展示
│   │   ├── InferenceView.vue     ← 在线推断（队列/网格/切割）
│   │   ├── ModelExport.vue       ← 模型转换
│   │   └── AnnotationConvert.vue ← 标注互转
│   └── api/
├── tools/
│   ├── cleanup_storage.py        ← 存储瘦身（保守模式）
│   ├── verify_cls.py             ← cls 模型全量验证
│   └── test_cls_pipeline.py      ← cls 端到端回归测试
├── start_all.bat / start_*.bat   ← 一键启动
└── storage/                 ← 数据存储（.gitignore）
    ├── uploads/             ← 原图
    ├── datasets/            ← 自动生成的 YOLO 训练集
    ├── runs/                ← 训练输出 / 推断结果
    └── exports/             ← 导出的模型文件
```

---

## 📖 详细部署指南

> 本节面向零基础用户，一步一步跟着做即可。
> 部署完成后，局域网内所有同事通过浏览器访问即可使用。

### 1. 环境要求

| 项目 | 要求 |
|------|------|
| 系统 | Windows 10/11（64 位） |
| 内存 | 8GB 以上（推荐 16GB） |
| 硬盘 | 至少 30GB 可用空间 |
| 显卡 | NVIDIA 显卡（可选，没有则用 CPU） |

### 2. 安装 Python

打开 https://www.python.org/downloads/，下载 **Python 3.11.x**。

> ⚠️ 不要下载 3.12 或 3.13，部分依赖不兼容

安装时**务必**勾选 ✅ `Add python.exe to PATH`。

验证：
```powershell
python --version  # 应显示 Python 3.11.x
```

### 3. 安装 Node.js

访问 https://nodejs.org/，下载 **LTS 版本**，一直 Next。

```powershell
node --version
npm --version
```

### 4. 安装 MySQL

下载：https://dev.mysql.com/downloads/mysql/ → MySQL Installer for Windows → Server only。

- 端口默认 3306
- Root 密码设为 `123456`（或自定义，记牢后面要用）
- 勾选 `Configure MySQL Server as a Windows Service`

创建数据库：
```powershell
mysql -u root -p123456 -e "CREATE DATABASE IF NOT EXISTS yolo_seg CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
```

### 5. 安装 Redis

下载：https://github.com/tporadowski/redis/releases → 最新的 `Redis-x64-xxx.msi`。

勾选 `Add to PATH` + `Install as Windows Service`，端口默认 6379。

```powershell
redis-cli ping  # 应返回 PONG
```

### 6. 部署后端

```powershell
# 解压到 D:\yolo26s_platform（路径中不要有中文或空格）
cd D:\yolo26s_platform
python -m venv venv
venv\Scripts\activate

# 安装依赖（约 5~10 分钟）
pip install -r server/requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
pip install openvino onnx onnxslim onnxruntime -i https://pypi.tuna.tsinghua.edu.cn/simple
```

**（可选）GPU 支持** — 如果有 NVIDIA 显卡：
```powershell
nvidia-smi  # 记录 CUDA 版本
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
```

**配置 .env**：
```powershell
copy .env.example .env
# 用记事本打开 .env，至少修改：
# DATABASE_URL = mysql+pymysql://root:你的密码@localhost:3306/yolo_seg?charset=utf8mb4
# JWT_SECRET = 改成随机字符串
```

**测试启动**：
```powershell
$env:YOLO_AUTOINSTALL="False"
uvicorn server.main:app --host 0.0.0.0 --port 8000
```

看到 "YOLO26s-Seg 标注训练平台 后端已启动" 即成功，按 Ctrl+C 停止。

### 7. 启动 Celery Worker

> ⚠️ 不启 Celery 训练任务会一直卡在"排队中"

新开一个 PowerShell：
```powershell
cd D:\yolo26s_platform
venv\Scripts\activate
set PYTHONPATH=D:\yolo26s_platform
celery -A server.tasks worker --loglevel=info --pool=solo
```

### 8. 部署前端

```powershell
cd D:\yolo26s_platform\web
npm install --registry https://registry.npmmirror.com
npx vite --host 0.0.0.0 --port 5174
```

浏览器打开 `http://localhost:5174` → 见到登录页即成功。

### 9. 配置开机自启

项目根目录已有 4 个启动脚本：

| 文件 | 作用 |
|------|------|
| `start_backend.bat` | 启动后端（端口 8000） |
| `start_celery.bat` | 启动 Celery 训练调度器 |
| `start_frontend.bat` | 启动前端（端口 5174） |
| `start_all.bat` | ✅ 一键启动全部 |

> 如果解压目录不是 `D:\yolo26s_platform`，需要用记事本编辑 4 个 bat 文件改路径。

**设置开机自启**：
1. `Win + R` 输入 `shell:startup` 回车
2. 右键 `start_all.bat` → 创建快捷方式 → 把快捷方式剪切到启动目录

### 10. 局域网访问

```powershell
ipconfig  # 找到 IPv4 地址，例如 192.168.1.100

# 管理员 PowerShell 放行端口
netsh advfirewall firewall add rule name="YOLO-Backend-8000" dir=in action=allow protocol=tcp localport=8000
netsh advfirewall firewall add rule name="YOLO-Frontend-5174" dir=in action=allow protocol=tcp localport=5174
```

同事访问 `http://192.168.1.100:5174`。建议本机设置静态 IP 避免变化。

### 11. 验证

| 功能 | 测试 |
|------|------|
| ✅ 登录 | admin / admin123 |
| ✅ 创建项目 | 项目管理 → 新建项目 |
| ✅ 上传图片 | 进入项目 → 上传图像 |
| ✅ 标注 | 点击图片进入标注器 |
| ✅ 训练 | 点训练模型 → 提交 |
| ✅ 推断 | 点在线推断 → 选图 |

---

## 🧰 日常维护

### 数据库备份

`backup.bat`：
```bat
@echo off
set BACKUP_DIR=D:\yolo26s_platform\backups
set DATE=%date:~0,4%%date:~5,2%%date:~8,2%
if not exist %BACKUP_DIR% mkdir %BACKUP_DIR%
mysqldump -u root -p123456 yolo_seg > %BACKUP_DIR%\backup_%DATE%.sql
echo 备份完成
pause
```

恢复：
```powershell
mysql -u root -p123456 yolo_seg < backups\backup_20260415.sql
```

### 存储瘦身

定期跑：
```powershell
python tools/cleanup_storage.py --dry-run   # 预览
python tools/cleanup_storage.py             # 执行
```

清理推断缓存、epoch checkpoints、预处理产物，保留最终模型与原图。

### 更新代码

1. 关闭 3 个启动窗口
2. `git pull` 或覆盖代码（保留 `.env` 和 `storage/`）
3. 双击 `start_all.bat` 重启

---

## ❓ 常见问题

| 问题 | 解决 |
|------|------|
| 同事访问不了 | 防火墙放行端口 + 同一局域网 |
| 端口被占用 | `netstat -ano \| findstr :8000` 找 PID → `taskkill /F /PID <PID>` |
| MySQL 连不上 | `net start mysql80` |
| Redis 连不上 | `net start redis` |
| 训练一直 pending | 检查 Celery 窗口是否在运行 |
| 推断很慢 | 选 GPU 设备 / 降低长边缩放 / 用 OpenVINO 模型 |
| 取消的任务还想用 | `storage\runs\task_<N>\runs\train\weights\best.pt` 直接选用 |

---

## 📝 数据库

```
mysql+pymysql://root:123456@localhost:3306/yolo_seg
```

**自动迁移**：每次启动后端会自动检查 `server/database.py` 中的 ALTER TABLE 列表并执行（`IF NOT EXISTS` 形式），改库结构只需追加迁移语句。

---

## 🔐 默认账号

| 账号 | 密码 | 角色 |
|------|------|------|
| admin | admin123 | 管理员 |

> ⚠️ 部署完成后请立即修改 admin 密码（登录后侧边栏底部 → 修改密码）。

---

## 📜 License

内部项目，非公开发行。
