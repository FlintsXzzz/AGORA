import os

import uvicorn

from main import app


if __name__ == "__main__":
    host = os.getenv("AGENT_HOST", "127.0.0.1")
    port = int(os.getenv("AGENT_PORT", "8087"))
    uvicorn.run(app, host=host, port=port)
