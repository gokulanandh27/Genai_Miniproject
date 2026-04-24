import sys
import asyncio
import uvicorn
from dotenv import load_dotenv

load_dotenv()

if __name__ == "__main__":
    # Force ProactorEventLoop before uvicorn initializes its loop
    if sys.platform.startswith("win"):
        import sys as _sys
        import io
        _sys.stdout = io.TextIOWrapper(_sys.stdout.buffer, encoding='utf-8')
        _sys.stderr = io.TextIOWrapper(_sys.stderr.buffer, encoding='utf-8')
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    
    # Run uvicorn programmatically
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
