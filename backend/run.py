import os
from pathlib import Path

import uvicorn

BACKEND_ROOT = Path(__file__).resolve().parent
# pytest / 飞轮等运行时产物目录（须在启动前存在，供 reload 排除）
RUNTIME_DIRS = [
    BACKEND_ROOT / "data",
    BACKEND_ROOT / "logs",
    BACKEND_ROOT.parent / ".runtime",
]
for directory in RUNTIME_DIRS:
    directory.mkdir(parents=True, exist_ok=True)

# uvicorn 会始终把 cwd 加入监视列表；排除目录必须用绝对路径才能匹配 watchfiles 事件
RELOAD_EXCLUDE_DIRS = [str(d.resolve()) for d in RUNTIME_DIRS]

if __name__ == "__main__":
    reload_enabled = os.getenv("AUTOTEST_DEV_RELOAD", "1").lower() in ("1", "true", "yes")
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8099,
        reload=reload_enabled,
        reload_dirs=["app"],
        reload_excludes=RELOAD_EXCLUDE_DIRS,
    )
