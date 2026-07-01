# -*- coding: utf-8 -*-
"""
YOLO26s-Seg 硅片缺陷标注与训练平台 — FastAPI 后端入口
=====================================================
启动方式:
    uvicorn server.main:app --reload --host 0.0.0.0 --port 8000

API 文档:
    http://localhost:8000/docs      (Swagger UI)
    http://localhost:8000/redoc     (ReDoc)
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# 提升 multipart 上传最大文件数（默认 1000，分类项目按文件夹导入会超）
try:
    from starlette.formparsers import MultiPartParser as _MPP
    _orig_init = _MPP.__init__
    def _patched_init(self, *args, **kwargs):
        kwargs['max_files'] = 100000
        kwargs['max_fields'] = 100000
        _orig_init(self, *args, **kwargs)
    _MPP.__init__ = _patched_init
except Exception as _e:
    print(f"[WARN] 无法 patch MultiPartParser: {_e}")

from .config import settings
from .database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时建表 + 创建默认管理员"""
    init_db()
    # 创建默认管理员
    from .database import SessionLocal
    from .services.auth_service import create_default_admin, is_using_default_secret
    db = SessionLocal()
    try:
        create_default_admin(db)
    finally:
        db.close()
    print("=" * 60)
    print("  YOLO26s-Seg 标注训练平台 后端已启动")
    print(f"  API 文档: http://localhost:{settings.PORT}/docs")
    print(f"  默认管理员: admin / admin123")
    if is_using_default_secret():
        print("  [!! 安全告警 !!] JWT_SECRET 未配置，正在使用编译进代码的默认密钥；")
        print("                    生产环境务必在 .env 中设置 JWT_SECRET=<随机长串>")
    print("=" * 60)
    yield


app = FastAPI(
    title="YOLO26s-Seg 标注训练平台",
    description="硅片缺陷检测：Web 标注 + 模型训练 + 推断服务",
    version="1.0.0",
    lifespan=lifespan,
)

# ---- CORS 配置 ----
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- 认证中间件 ----
import re
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from .services.auth_service import decode_token

# 不需要认证的路径
AUTH_WHITELIST = {"/api/auth/login", "/api/health", "/docs", "/redoc", "/openapi.json"}

# 管理员专属动作：普通用户(role=user)命中则 403。集中在此便于审计。
# 普通用户仍可 上传/标注/训练/推理/看数据/导出项目数据包；下列为"删除·改结构·导出模型·导入合并"等敏感动作。
_ADMIN_ONLY = [
    ("POST",   re.compile(r"^/api/projects$")),                       # 新建项目
    ("PUT",    re.compile(r"^/api/projects/\d+$")),                   # 改项目设置
    ("DELETE", re.compile(r"^/api/projects/\d+$")),                   # 删项目
    ("POST",   re.compile(r"^/api/projects/import-package$")),        # 导入项目包
    ("POST",   re.compile(r"^/api/projects/\d+/merge-package$")),     # 合并标注包
    ("POST",   re.compile(r"^/api/projects/\d+/convert-task-type$")), # 转换任务类型
    ("POST",   re.compile(r"^/api/projects/\d+/classes$")),           # 新增缺陷类别
    ("PUT",    re.compile(r"^/api/projects/\d+/classes/\d+$")),       # 修改缺陷类别
    ("DELETE", re.compile(r"^/api/projects/\d+/classes/\d+$")),       # 删除缺陷类别
    ("DELETE", re.compile(r"^/api/images/\d+$")),                     # 删除单张图
    ("POST",   re.compile(r"^/api/images/batch-delete$")),            # 批量删图
    ("DELETE", re.compile(r"^/api/train/tasks/\d+$")),                # 删训练任务
    ("POST",   re.compile(r"^/api/export/run$")),                     # 导出模型
    ("DELETE", re.compile(r"^/api/export/\d+$")),                     # 删导出记录
    ("GET",    re.compile(r"^/api/export/download/")),                # 下载模型(.pt/导出件)
    ("POST",   re.compile(r"^/api/import/")),                         # 批量导入标注(VOC/cls 等)
]


def _is_admin_only(method: str, path: str) -> bool:
    return any(method == m and pat.match(path) for m, pat in _ADMIN_ONLY)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path
        # 只对 /api/* 做鉴权；前端页面/assets/SPA 路由/静态图(/static)/文档 一律放行。
        # 敏感资源（图片文件、模型下载）都在 /api/ 下，仍受保护。
        skip_auth = (
            not path.startswith("/api/")
            or path in AUTH_WHITELIST          # /api/auth/login、/api/health
        )
        if skip_auth:
            return await call_next(request)
        # token 支持 Authorization 头 或 ?token=（供 <img>/<a>/window.open 等浏览器原生请求带鉴权）
        auth = request.headers.get("Authorization", "")
        token = auth[7:] if auth.startswith("Bearer ") else request.query_params.get("token", "")
        token_data = decode_token(token) if token else None
        if not token_data:
            return JSONResponse(status_code=401, content={"detail": "未登录或登录已过期"})
        # 角色校验：普通用户禁止管理员专属动作
        if token_data.get("role") != "admin" and _is_admin_only(request.method, path):
            return JSONResponse(status_code=403, content={"detail": "该操作需要管理员权限"})
        return await call_next(request)


app.add_middleware(AuthMiddleware)

# ---- 注册路由 ----
from .routers import projects, images, annotations, train, inference, export, import_data, auth

app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(images.router)
app.include_router(annotations.router)
app.include_router(train.router)
app.include_router(inference.router)
app.include_router(export.router)
app.include_router(import_data.router)

# ---- 静态文件（推断结果图片）----
import os
_storage = str(settings.runs_path.parent)
if os.path.isdir(_storage):
    app.mount("/static/storage", StaticFiles(directory=_storage), name="storage_static")


# ---- 健康检查 ----
@app.get("/api/health", tags=["系统"])
def health_check():
    return {"status": "ok", "service": "yolo26s-seg-platform"}


# ---- 前端静态托管（生产部署）----
# web 目录 `npm run build` 出 web/dist，由后端一并提供页面：
# 目标机无需装 node/vite，打开 http://<host>:8000 即用（离线锁死部署用这个）。
# dist 不存在则跳过（开发环境走 vite dev）。此段必须在所有 /api 路由之后注册。
from fastapi import HTTPException
from fastapi.responses import FileResponse
from pathlib import Path as _Path

_dist = _Path(__file__).resolve().parent.parent / "web" / "dist"
if _dist.is_dir():
    _assets = _dist / "assets"
    if _assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(_assets)), name="fe_assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def _serve_spa(full_path: str):
        # /api 与 /static 交给各自的路由/挂载；其余一律回 SPA 入口
        if full_path.startswith("api/") or full_path.startswith("static/"):
            raise HTTPException(status_code=404, detail="Not Found")
        f = (_dist / full_path).resolve()
        if full_path and f.is_file() and f.is_relative_to(_dist):
            return FileResponse(str(f))                       # favicon.ico / vite.svg 等根文件
        return FileResponse(str(_dist / "index.html"))        # SPA 入口（/login、/project/x 等前端路由）


# ---- 启动入口 ----
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "server.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
