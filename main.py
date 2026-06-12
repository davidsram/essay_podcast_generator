"""启动入口。"""
import uvicorn
from app.config import settings


def main() -> None:
    uvicorn.run(
        "app.server:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
