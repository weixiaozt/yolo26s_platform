# YOLO26s-Seg 硅片缺陷检测平台 — Windows 部署教程

> 本教程面向零基础用户，一步一步跟着做即可。
> 部署完成后，局域网内所有同事通过浏览器访问即可使用。

---

## 目录

1. [环境要求](#1-环境要求)
2. [安装 Python](#2-安装-python)
3. [安装 Node.js](#3-安装-nodejs)
4. [安装 MySQL](#4-安装-mysql)
5. [安装 Redis](#5-安装-redis)
6. [部署后端](#6-部署后端)
7. [启动 Celery Worker](#7-启动-celery-worker)
8. [部署前端](#8-部署前端)
9. [配置开机自启](#9-配置开机自启)
10. [局域网访问配置](#10-局域网访问配置)
11. [验证部署](#11-验证部署)
12. [日常维护](#12-日常维护)
13. [常见问题](#13-常见问题)

---

## 1. 环境要求

| 项目 | 要求 |
|------|------|
| 系统 | Windows 10/11（64 位） |
| 内存 | 8GB 以上（推荐 16GB） |
| 硬盘 | 至少 30GB 可用空间 |
| 显卡 | NVIDIA 显卡（可选，没有则用 CPU） |

---

## 2. 安装 Python

### 2.1 下载

打开浏览器，访问：https://www.python.org/downloads/

下载 **Python 3.11.x**（点击 Download Python 3.11.x 按钮）

> ⚠️ 不要下载 3.12 或 3.13，部分依赖不兼容

### 2.2 安装

1. 双击安装包
2. **重要**：勾选底部的 ✅ `Add python.exe to PATH`
3. 点击 `Install Now`
4. 等待安装完成

### 2.3 验证

打开 PowerShell（Win + X → Windows PowerShell），输入：

```powershell
python --version
```

应显示 `Python 3.11.x`

---

## 3. 安装 Node.js

### 3.1 下载

访问：https://nodejs.org/

下载 **LTS 版本**（左边那个绿色按钮）

### 3.2 安装

双击安装包，一直 Next 即可，所有选项保持默认。

### 3.3 验证

```powershell
node --version
npm --version
```

---

## 4. 安装 MySQL

### 4.1 下载

访问：https://dev.mysql.com/downloads/mysql/

选择 `MySQL Installer for Windows`，下载 Full 版

### 4.2 安装

1. 运行安装器，选 `Server only`
2. 端口保持默认 `3306`
3. Root 密码设为：`123456`（或自定义，后面要用）
4. 勾选 `Configure MySQL Server as a Windows Service`（开机自启）
5. 完成安装

### 4.3 创建数据库

打开 PowerShell，输入：

```powershell
mysql -u root -p123456 -e "CREATE DATABASE IF NOT EXISTS yolo_seg CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
```

看到无报错即成功。

### 4.4 验证

```powershell
mysql -u root -p123456 -e "SHOW DATABASES;"
```

应能看到 `yolo_seg`。

---

## 5. 安装 Redis

### 5.1 下载

访问：https://github.com/tporadowski/redis/releases

下载最新的 `Redis-x64-xxx.msi`

### 5.2 安装

1. 双击 MSI 安装
2. 勾选 `Add the Redis installation folder to the PATH`
3. 勾选 `Install Redis as a Windows Service`（开机自启）
4. 端口保持默认 `6379`
5. 完成安装

### 5.3 验证

```powershell
redis-cli ping
```

应返回 `PONG`

---

## 6. 部署后端

### 6.1 解压项目

将 `yolo26s_platform.zip` 解压到 `D:\yolo26s_platform\`

> 路径中不要有中文或空格

### 6.2 创建虚拟环境

```powershell
cd D:\yolo26s_platform
python -m venv venv
venv\Scripts\activate
```

看到命令行前面出现 `(venv)` 即成功。

### 6.3 安装 Python 依赖

```powershell
pip install -r server/requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

等待安装完成（约 5~10 分钟）。

### 6.4 安装推断/导出依赖

```powershell
pip install openvino onnx onnxslim onnxruntime -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 6.5（可选）安装 GPU 支持

> 如果没有 NVIDIA 显卡，跳过这一节，平台会自动使用 CPU。

**第一步：安装 NVIDIA 驱动和 CUDA**

访问 NVIDIA 驱动下载页：https://www.nvidia.com/Download/index.aspx

选择你的显卡型号下载并安装。安装完后打开 PowerShell 验证：

```powershell
nvidia-smi
```

能看到显卡信息说明驱动安装成功，记录 `CUDA Version` 的数字（例如 12.4）。

**第二步：安装 GPU 版 PyTorch**

```powershell
# CUDA 12.4 及以上用这个：
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
```

> 安装约 2.5GB，耐心等待。

### 6.6 创建 .env 配置文件

项目已包含 `.env.example`，复制一份改名即可：

```powershell
cd D:\yolo26s_platform
copy .env.example .env
```

然后用记事本打开 `.env`，**至少修改以下两项**：

```ini
# 1. 数据库密码改成你安装 MySQL 时设的密码
DATABASE_URL=mysql+pymysql://root:123456@localhost:3306/yolo_seg?charset=utf8mb4

# 2. JWT 密钥改成随机字符串（保密，别让人知道），如果报错，请注释JWT或删除JWT配置
JWT_SECRET=your_company_secret_key_change_this_to_something_random
```

> 其他配置（Redis、端口、CORS）保持默认即可。

### 6.7 测试后端启动

```powershell
cd D:\yolo26s_platform
venv\Scripts\activate
$env:YOLO_AUTOINSTALL="False"; uvicorn server.main:app --host 0.0.0.0 --port 8000
```

看到以下信息说明成功：

```
============================================================
  YOLO26s-Seg 标注训练平台 后端已启动
  API 文档: http://localhost:8000/docs
  默认管理员: admin / admin123
============================================================
```

按 `Ctrl+C` 停止（后面会配置自动启动）。

---

## 7. 启动 Celery Worker

> ⚠️ Celery Worker 是训练任务的核心调度器，**不启动则训练任务会一直卡在"排队中"**，标注和推断功能不受影响。

### 7.1 启动 Celery

新打开一个 PowerShell 窗口，执行：

```powershell
cd D:\yolo26s_platform
venv\Scripts\activate
set PYTHONPATH=D:\yolo26s_platform
celery -A server.tasks worker --loglevel=info --pool=solo
```

看到以下信息说明启动成功：

```
[tasks]
  . server.tasks.train_model
  . server.tasks.run_inference

[2026-xx-xx xx:xx:xx,xxx: INFO/MainProcess] celery@hostname ready.
```

> Celery 窗口需要一直保持运行，关闭窗口即停止训练调度。

---

## 8. 部署前端（不要漏这一步）

### 7.1 安装前端依赖

```powershell
cd D:\yolo26s_platform\web
npm install --registry https://registry.npmmirror.com
```

### 7.2 修改前端配置（生产模式）

编辑 `D:\yolo26s_platform\web\vite.config.ts`，确保代理配置正确：

```typescript
proxy: {
  '/api': {
    target: 'http://localhost:8000',
    changeOrigin: true,
  },
  '/static/storage': {
    target: 'http://localhost:8000',
    changeOrigin: true,
  },
},
```

> 这个配置通常已经是对的，不需要改。

### 7.3 测试前端启动

```powershell
cd D:\yolo26s_platform\web
npx vite --host 0.0.0.0 --port 5174
```

浏览器打开 `http://localhost:5174`，能看到登录页说明成功。

按 `Ctrl+C` 停止。

---

## 9. 配置开机自启

### 9.1 启动脚本说明

项目根目录已包含 4 个启动脚本，**无需手动创建**：

| 文件 | 作用 |
|------|------|
| `start_backend.bat` | 启动后端 API（端口 8000） |
| `start_celery.bat` | 启动 Celery 训练调度器 |
| `start_frontend.bat` | 启动前端（端口 5174） |
| `start_all.bat` | 一键启动全部 ✅ 推荐使用 |

> ⚠️ 脚本中路径硬编码为 `D:\yolo26s_platform`，如果你解压到了其他目录，需要用记事本打开 4 个 bat 文件，将路径替换为实际路径。

### 9.2 设置开机自启

1. 按 `Win + R`，输入 `shell:startup`，回车
2. 打开了一个文件夹（启动目录）
3. 右键 `start_all.bat` → 创建快捷方式
4. 把快捷方式剪切到刚打开的启动目录

这样每次开机会自动启动全部服务。

### 9.3 手动启动/停止

- **启动**：双击 `start_all.bat`
- **停止**：关闭 3 个黑色命令行窗口（Backend / Celery Worker / Frontend）

---

## 10. 局域网访问配置

### 10.1 查看本机 IP

```powershell
ipconfig
```

找到 `以太网适配器` 或 `无线局域网适配器` 下的 `IPv4 地址`，例如：`192.168.1.100`

### 10.2 防火墙放行

管理员 PowerShell 执行：

```powershell
# 放行后端
netsh advfirewall firewall add rule name="YOLO-Backend-8000" dir=in action=allow protocol=tcp localport=8000

# 放行前端
netsh advfirewall firewall add rule name="YOLO-Frontend-5174" dir=in action=allow protocol=tcp localport=5174
```

### 10.3 同事访问

告诉同事在浏览器打开：

```
http://192.168.1.100:5174
```

（把 192.168.1.100 换成你的实际 IP）

### 10.4 固定 IP（推荐）

为了避免 IP 变化，建议设置静态 IP：

1. 控制面板 → 网络和共享中心 → 更改适配器设置
2. 右键你的网卡 → 属性 → Internet 协议版本 4 (TCP/IPv4)
3. 选择「使用下面的 IP 地址」：
   - IP 地址：`192.168.1.100`（改成你局域网网段的一个空闲 IP）
   - 子网掩码：`255.255.255.0`
   - 默认网关：`192.168.1.1`（通常是路由器地址）
   - DNS：`8.8.8.8`

---

## 11. 验证部署

### 11.1 本机测试

1. 双击 `start_all.bat` 启动所有服务
2. 浏览器打开 `http://localhost:5174`
3. 用 `admin / admin123` 登录
4. 能看到项目管理页面 → 成功

### 11.2 局域网测试

1. 让同事打开浏览器
2. 访问 `http://你的IP:5174`
3. 能看到登录页 → 成功

### 11.3 功能检查清单

| 功能 | 测试方法 |
|------|---------|
| ✅ 登录 | admin / admin123 |
| ✅ 创建项目 | 首页点「新建项目」 |
| ✅ 上传图片 | 进入项目 → 上传图像 |
| ✅ 标注 | 点击图片进入标注器 |
| ✅ 训练 | 点「训练模型」→ 提交 |
| ✅ 推断 | 点「在线推断」→ 选图 |
| ✅ 用户管理 | 侧边栏「用户管理」 |

---

## 12. 日常维护

### 12.1 数据库备份

创建 `D:\yolo26s_platform\backup.bat`：

```bat
@echo off
set BACKUP_DIR=D:\yolo26s_platform\backups
set DATE=%date:~0,4%%date:~5,2%%date:~8,2%
if not exist %BACKUP_DIR% mkdir %BACKUP_DIR%
mysqldump -u root -p123456 yolo_seg > %BACKUP_DIR%\backup_%DATE%.sql
echo 备份完成: %BACKUP_DIR%\backup_%DATE%.sql
pause
```

双击即可备份。建议每周备份一次。

### 12.2 数据库恢复

```powershell
mysql -u root -p123456 yolo_seg < D:\yolo26s_platform\backups\backup_20260415.sql
```

### 12.3 更新代码

1. 停止所有服务（关闭 3 个窗口）
2. 用新的文件覆盖 `D:\yolo26s_platform\`（保留 `.env` 和 `storage` 文件夹）
3. 双击 `start_all.bat` 重新启动

### 12.4 查看磁盘占用

```powershell
# 查看 storage 文件夹大小
dir D:\yolo26s_platform\storage /s
```

训练模型和推断图片会占用磁盘，定期清理不需要的训练记录。

---

## 13. 常见问题

### Q: 同事访问不了？

1. 确认服务已启动（3 个黑色窗口在运行）
2. 确认防火墙已放行（第 9.2 步）
3. 确认同事和你在同一个局域网
4. 让同事 ping 你的 IP：`ping 192.168.1.100`

### Q: 启动报错 "端口被占用"？

```powershell
# 查看谁占用了 8000 端口
netstat -ano | findstr :8000
# 杀掉占用的进程（PID 换成上面查到的）
taskkill /F /PID 12345
```

### Q: MySQL 连接失败？

检查 MySQL 服务是否在运行：

```powershell
net start mysql80
```

### Q: Redis 连接失败？

```powershell
net start redis
```

### Q: 训练任务一直 pending？

检查 Celery 窗口是否在运行。如果关掉了，双击 `start_celery.bat`。

### Q: 电脑重启后服务没有自动启动？

检查 `start_all.bat` 的快捷方式是否在启动目录：
按 `Win + R` → 输入 `shell:startup` → 确认快捷方式在里面。

### Q: 推断很慢？

- 有 NVIDIA 显卡 → 推断页面选 GPU 设备
- 设置「长边缩放」为 1024 或 2048
- 使用 OpenVINO 格式模型（模型转换页面转换）

---

## 附录：完整目录结构

```
D:\yolo26s_platform\
├── .env.example            ← 配置模板（复制为 .env 后修改）
├── .env                    ← 实际配置文件（需要手动从 .env.example 复制创建）
├── start_all.bat           ← 一键启动全部 ✅
├── start_backend.bat       ← 后端启动脚本
├── start_celery.bat        ← Celery 训练调度器脚本
├── start_frontend.bat      ← 前端启动脚本
├── yolo26s-seg.pt          ← 预训练权重（实例分割，推荐）
├── yolo26n.pt              ← 预训练权重（最小型）
├── yolo26l-seg.pt          ← 预训练权重（大模型）
├── venv\                   ← Python 虚拟环境（需要手动创建）
├── core\                   ← 核心算法模块（预处理、训练、推断）
├── server\                 ← 后端 API 代码
├── web\                    ← 前端代码
└── storage\                ← 数据存储
    ├── uploads\            ← 上传的原图
    ├── datasets\           ← YOLO 训练数据集（自动生成）
    ├── runs\               ← 训练输出/推断结果
    └── exports\            ← 导出的模型文件
```

---

## 附录：账号说明

| 账号 | 密码 | 角色 | 用途 |
|------|------|------|------|
| admin | admin123 | 管理员 | 管理用户、所有功能 |
| （自建） | （自定） | 普通用户 | 标注、训练、推断 |

> ⚠️ 部署完成后请立即修改 admin 密码！
> 操作：登录后 → 侧边栏底部 → 修改密码
