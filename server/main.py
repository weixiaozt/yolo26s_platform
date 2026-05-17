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
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from .services.auth_service import decode_token

# 不需要认证的路径
AUTH_WHITELIST = {"/api/auth/login", "/api/health", "/docs", "/redoc", "/openapi.json"}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path
        # 不需要认证的路径
        skip_auth = (
            path in AUTH_WHITELIST
            or path.startswith("/static/")
            or path.startswith("/api/auth/login")
            or path.startswith("/api/images/") and "/file" in path   # 图片缩略图/原图
            or path.startswith("/api/inference/image/")               # 推断结果图片
            or path.startswith("/api/export/download/")               # 模型下载
        )
        if skip_auth:
            return await call_next(request)
        # 检查 token
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token_data = decode_token(auth[7:])
            if token_data:
                return await call_next(request)
        return JSONResponse(status_code=401, content={"detail": "未登录或登录已过期"})


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


# ---- 启动入口 ----
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "server.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
