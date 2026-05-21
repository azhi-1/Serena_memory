from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from api import review_router, browse_router, maintenance_router, settings_router
from auth import BearerTokenAuthMiddleware, get_cors_config
from namespace_middleware import NamespaceMiddleware
from locales.middleware import LocaleMiddleware
from db import get_db_manager, close_db
from health import router as health_router
import argparse
import os
import config as _cfg
from config import ConfigWriteError
from auth import enforce_network_auth

# 正式启动路径只有 python main.py，host 从 config 读。
# 但仍需嗅探 uvicorn CLI 的覆盖源，遇到公网无 token 时直接拒绝启动。
_parser = argparse.ArgumentParser(add_help=False)
_parser.add_argument("--host", type=str)
_args, _ = _parser.parse_known_args()
_host = _args.host or os.environ.get("UVICORN_HOST") or _cfg.get("host")
enforce_network_auth(host=_host)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时
    print("Memory API starting...")

    _cfg.ensure_config_exists()

    # Initialize Database
    try:
        db_manager = get_db_manager()
        await db_manager.init_db()
        print("Database initialized.")
    except Exception as e:
        print(f"Failed to initialize database: {e}")

    yield

    # 关闭时
    print("Closing database connections...")
    await close_db()


app = FastAPI(
    title="Knowledge Graph API",
    description="AI长期记忆知识图谱后端",
    version="2.5.1",
    lifespan=lifespan,
)

app.add_middleware(
    BearerTokenAuthMiddleware,
    excluded_paths=["/health"],
)

app.add_middleware(LocaleMiddleware)

app.add_middleware(NamespaceMiddleware)

app.add_middleware(
    CORSMiddleware,
    **get_cors_config(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(health_router)
app.include_router(review_router)
app.include_router(browse_router)
app.include_router(maintenance_router)
app.include_router(settings_router)


@app.exception_handler(ConfigWriteError)
async def config_write_error_handler(request: Request, exc: ConfigWriteError):
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc)},
    )


@app.get("/")
async def root():
    """根路径"""
    return {"message": "Knowledge Graph API", "version": "2.5.1", "docs": "/docs"}


if __name__ == "__main__":
    import uvicorn

    host = _cfg.get("host")
    port = int(_cfg.get("web_port"))
    enforce_network_auth(host=host)
    uvicorn.run(app, host=host, port=port)
