# VP-Vision 离线受控部署说明（GTX 1050 Ti）

适用目标：一台不能访问外网的 Windows 电脑，部署目录固定为 `D:\vp-vision`，后端业务代码不以 `.py` 明文交付，普通平台账号除删除项目外可正常使用，模型权重按只读资产管理，并启用机器码绑定。

## 交付包内容

离线包名称类似：

```text
vp-vision_offline_1050ti_YYYYMMDD_<commit>.zip
```

解压后目录结构：

```text
D:\vp-vision\
  app\                 后端业务 pyc-only 包，不包含 server/core 的 .py 明文
  web\dist\            前端构建产物
  venv\                已安装依赖的 Python 环境
  runtime\
    mariadb\           内置 MariaDB 10.11 LTS 便携运行时
    mariadb-data\      首次初始化后生成的数据库数据目录
  storage\             数据、上传图片、训练结果、模型权重
  config\
    .env               离线部署配置
    license.dat        机器授权文件，需由管理员生成后放入
  logs\
  tools\
    get_machine_code.bat
    vpvision_get_machine_code.py
    init_database.bat
    start_database.bat
    ensure_database.bat
    start_api.bat
    start_worker.bat
    start_all.bat
    smoke_test.bat
    gpu_check.bat
  README_FIRST.md
```

包内不包含 `.git`、后端 `.py` 源码、开发日志、当前机器 `.env`、历史数据、node_modules 源码工程。

## 部署前准备

目标电脑需要提前确认：

- Windows 10/11 64 位
- D 盘有足够空间，建议至少 30GB 可用
- NVIDIA 驱动已安装
- 显卡为 GTX 1050 Ti，通常 4GB 显存

目标电脑不能联网，所以不要在目标机上执行 `pip install`、`npm install` 或 Ultralytics 自动下载模型。本包已内置 MariaDB 10.11 LTS 便携运行时，Celery 使用本地文件队列，不要求目标机预装 MySQL 或 Redis。

## 1050 Ti 注意事项

GTX 1050 Ti 是 Pascal 架构，CUDA Compute Capability 为 `sm_61`。离线环境必须验证 PyTorch CUDA 包支持 `sm_61`。

部署后运行：

```cmd
D:\vp-vision\tools\gpu_check.bat
```

预期结果：

```text
cuda available: True
device count: 1
device 0: NVIDIA GeForce GTX 1050 Ti
```

如果显示 `False` 或出现 `sm_61 is not compatible`，说明当前 PyTorch/CUDA 运行包不适合 1050 Ti。需要重新准备支持 `sm_61` 的离线 torch/torchvision 环境，优先选择保守的 CUDA 11.8 系列 wheel，并在同类显卡上重新验证。

1050 Ti 默认建议：

- 推理优先 CUDA，失败可回退 CPU
- 训练 `batch=1` 起步
- 大图滑窗避免过高并发
- 分类任务压力较小
- seg/obb 训练显存压力大，必要时降低 `imgsz`
- FP16 不强依赖，1050 Ti 没有 Tensor Core

## 机器码绑定流程

目标机第一次部署时还没有 `license.dat`，后端会因为授权缺失拒绝启动。先采集机器码：

```cmd
D:\vp-vision\tools\get_machine_code.bat
```

把输出的 `VP-Vision machine code` 发给管理员。

管理员在打包机或管理机上执行：

```cmd
D:\yolo26s_platform\venv\Scripts\python.exe D:\yolo26s_platform\tools\vpvision_make_license.py ^
  --machine-code <目标机机器码> ^
  --customer "公司离线电脑-1050Ti" ^
  --out D:\license.dat
```

私钥默认路径：

```text
D:\vpvision_license_private_key.pem
```

注意：私钥只能由管理员保管，不要复制到目标电脑。

生成后，把 `license.dat` 复制到：

```text
D:\vp-vision\config\license.dat
```

后端启动时会校验：

- license 签名是否合法
- license 里的机器码是否等于当前电脑机器码
- 如设置了过期时间，是否仍在有效期内

## 平台账号权限

平台内置两类角色：

- `admin`：管理员账号，由你保管
- `user`：普通账号，给目标电脑使用者

普通账号策略：

- 可以新建项目
- 可以导入项目/标注
- 可以上传图片
- 可以标注、修改标注、删除图片
- 可以训练
- 可以推理
- 可以导出/下载项目数据
- 不可以删除项目
- 不可以删除训练任务，因为会移除训练权重
- 不可以删除导出模型记录，因为会移除模型产物
- 不能进入用户管理，用户管理接口仍由管理员控制

前端会隐藏普通用户无权使用的删除按钮；后端中间件仍会强制拦截，不能只依赖前端。

## 模型权重只读策略

模型权重作为平台资产管理：

- 普通用户可以通过平台选择模型进行推理
- 普通用户可以下载允许下载的模型或导出件
- 普通用户不能删除项目
- 普通用户不能删除训练任务
- 普通用户不能删除导出模型记录

如果需要更强保护，可在目标电脑上把 `D:\vp-vision\storage` 设置为只有服务账号可写，普通 Windows 登录用户不直接访问文件夹。

## 安装步骤

1. 以管理员身份登录目标电脑。

2. 解压部署包到：

   ```text
   D:\vp-vision
   ```

3. 检查配置文件：

   ```text
   D:\vp-vision\config\.env
   ```

   关键配置：

   ```env
   DATABASE_URL=mysql+pymysql://root:123456@127.0.0.1:3307/yolo_seg?charset=utf8mb4
   CELERY_BROKER_URL=filesystem://
   CELERY_RESULT_BACKEND=rpc://
   CELERY_FILESYSTEM_BROKER_DIR=D:\vp-vision\storage\celery-broker
   STORAGE_ROOT=D:\vp-vision\storage
   VPVISION_LICENSE_REQUIRED=True
   VPVISION_LICENSE_FILE=D:\vp-vision\config\license.dat
   YOLO_AUTOINSTALL=False
   ```

4. 采集机器码，生成并放入 `license.dat`。

5. 启动全部服务：

   ```cmd
   D:\vp-vision\tools\start_all.bat
   ```

   它会自动完成：

   - 初始化 `D:\vp-vision\runtime\mariadb-data`
   - 在 `127.0.0.1:3307` 启动内置 MariaDB
   - 创建 `yolo_seg` 数据库
   - 启动后端 API
   - 启动 Celery Worker

   第一次启动后端会自动建表和执行字段迁移。

6. 打开浏览器：

   ```text
   http://localhost:8000
   ```

7. 管理员登录，创建普通用户账号。

   默认管理员账号仍为：

   ```text
   admin / admin123
   ```

   首次部署后请立刻修改管理员密码。

## 启动脚本

后端 API：

```cmd
D:\vp-vision\tools\start_api.bat
```

内置 MariaDB：

```cmd
D:\vp-vision\tools\start_database.bat
```

Celery Worker：

```cmd
D:\vp-vision\tools\start_worker.bat
```

一键启动：

```cmd
D:\vp-vision\tools\start_all.bat
```

GPU 验证：

```cmd
D:\vp-vision\tools\gpu_check.bat
```

基础冒烟测试：

```cmd
D:\vp-vision\tools\smoke_test.bat
```

## 验证清单

部署完成后按顺序验证：

- 后端日志出现 license OK
- MariaDB 窗口显示 ready for connections
- 后端日志出现 Application startup complete
- 浏览器能打开 `http://localhost:8000`
- `admin` 可登录
- 管理员能创建普通用户
- 普通用户能新建项目
- 普通用户看不到“删除项目”按钮
- 普通用户调用删除项目接口返回 403
- GPU 检测能看到 GTX 1050 Ti
- 在线推理可以跑一张小图
- 训练任务建议先用小数据集、`batch=1` 试跑

## 常见问题

### 已知待修复：训练任务一直显示“排队中”

2026-07-28 确认当前 filesystem broker 版离线包存在以下缺陷，需与后续源码改动一起合并后重新打包：

- Windows 下 Kombu 的 `filesystem://` transport 依赖 `pywintypes`、`win32con`、`win32file`，当前离线 venv 未携带 `pywin32`。
- API 先保存 `pending` 任务再投递 Celery；投递失败后没有把任务改成 `failed`，页面因此持续显示排队中。
- 当前 `smoke_test.bat` 没有测试 broker 连接和任务投递，无法在交付前发现该问题。

修复验收要求：

1. 离线 venv 中能正常 `import pywintypes, win32con, win32file`。
2. API 与 worker 使用同一个 `D:\vp-vision\storage\celery-broker`，完成一次真实任务投递和消费。
3. broker 不可用时，创建接口给出中文“训练队列不可用”，数据库任务进入 `failed` 而非永久 `pending`。
4. 修复前产生的排队任务需要删除/取消并重新创建，不会自动恢复。

### 后端启动报 license file not found

还没有把 `license.dat` 放到：

```text
D:\vp-vision\config\license.dat
```

先运行 `get_machine_code.bat`，把机器码发给管理员生成授权。

### ensure_database.bat 一直等待 MariaDB

先单独运行：

```cmd
D:\vp-vision\tools\start_database.bat
```

如果初始化失败，看：

```text
D:\vp-vision\runtime\mariadb-data\
```

目录下的 `.err` 日志。常见原因是 3307 端口被占用，可以修改 `config\.env` 和 `tools\*.bat` 中的端口，但要保持一致。

### 后端启动报 license is not valid for this machine

`license.dat` 不是为这台电脑生成的，或者目标机硬件信息变化导致机器码变化。重新采集机器码并签发。

### 后端启动卡在 Ultralytics 自动安装

确认 `.env` 或启动脚本里有：

```env
YOLO_AUTOINSTALL=False
```

### 普通用户仍能删除项目

确认后端是新包，且浏览器强制刷新。真正权限在后端中间件，普通用户删除接口应返回 403。

### 1050 Ti CUDA 不可用

检查 NVIDIA 驱动，然后运行：

```cmd
D:\vp-vision\tools\gpu_check.bat
```

如果 torch 报不支持 `sm_61`，需要换支持 1050 Ti 的离线 torch 包后重新打包。
