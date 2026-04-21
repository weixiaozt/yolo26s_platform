# 快速启动指南

## 前提条件

- Docker Desktop 已安装并运行
- Python 3.9+ 已安装
- Node.js 18+ 已安装

---

## 第一步：解压并进入项目

```bash
unzip yolo26s_platform.zip
cd yolo26s_platform
```

---

## 第二步：启动 MySQL + Redis

```bash
docker compose up -d
```

等待 ~10 秒让 MySQL 初始化完成。可以用以下命令确认：

```bash
docker compose ps
# 两个容器都应该是 running 状态
```

验证 MySQL 连接（可选）：

```bash
docker exec -it yolo_mysql mysql -uroot -pyolo26seg -e "SHOW DATABASES;"
# 应该能看到 yolo_seg 数据库
```

---

## 第三步：启动后端

```bash
# 安装 Python 依赖
pip install -r server/requirements.txt

# 复制环境变量配置
cp .env.example .env

# 启动 FastAPI（首次启动会自动建表）
uvicorn server.main:app --reload --host 0.0.0.0 --port 8000
```

看到以下输出说明后端启动成功：

```
============================================================
  YOLO26s-Seg 标注训练平台 后端已启动
  API 文档: http://localhost:8000/docs
============================================================
```

**打开浏览器访问 http://localhost:8000/docs** 确认 Swagger 文档能加载。

---

## 第四步：启动前端（新开一个终端）

```bash
cd yolo26s_platform/web
npm install
npm run dev
```

看到以下输出：

```
  VITE v5.x.x  ready in xxx ms
  ➜  Local:   http://localhost:5173/
```

---

## 第五步：打开浏览器使用

访问 **http://localhost:5173**

操作流程：

1. 点击「新建项目」→ 填写名称 → 点击「创建」
2. 点击项目卡片进入详情页
3. 点击「上传图像」→ 拖入你的硅片图像（BMP/PNG/JPG）
4. 点击任意缩略图 → 进入标注编辑器
5. 选择类别 → 点击画多边形 → 双击完成 → Ctrl+S 保存

---

## 快捷键（标注编辑器）

| 快捷键 | 功能 |
|--------|------|
| 鼠标点击 | 添加多边形顶点 |
| 双击 / Enter | 完成当前多边形 |
| Esc | 取消当前绘制 |
| Ctrl+S | 保存标注 |
| Ctrl+Z | 撤销 |
| Ctrl+Y | 重做 |
| A / ← | 上一张图像 |
| D / → | 下一张图像 |
| 滚轮 | 缩放画布 |
| Alt+拖拽 / 右键拖拽 | 平移画布 |
| 双击画布 | 重置视图 |

---

## 常见问题

### Q: 后端启动报 "Can't connect to MySQL"

MySQL 还没完全启动。等几秒后重试，或：

```bash
docker compose logs mysql
# 看到 "ready for connections" 说明就绪了
```

### Q: npm install 报错

确保 Node.js 版本 >= 18：

```bash
node -v
```

### Q: 上传图像后缩略图不显示

检查后端终端有没有报错。确认 `storage/uploads/` 目录有写权限。

### Q: 想用自己的 MySQL（不用 Docker）

编辑 `.env` 文件，修改 DATABASE_URL：

```
DATABASE_URL=mysql+pymysql://用户名:密码@主机:3306/数据库名?charset=utf8mb4
```
