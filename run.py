import sys
import asyncio
import io

if sys.platform.startswith("win"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import uvicorn
from dotenv import load_dotenv

load_dotenv()

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8000,
        reload=False,          # disable reload — avoids double-import issues on Windows
        log_level="info",
    )
