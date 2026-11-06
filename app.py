"""Starts the complexity agent:  python app.py"""
import uvicorn

from complexity_agent.config import settings

if __name__ == "__main__":
    print(f"Complexity agent on http://{settings.host}:{settings.port}  (open it to paste a key and try it)")
    uvicorn.run("complexity_agent.api:app", host=settings.host, port=settings.port, reload=settings.reload)
