import os
import sys
from pathlib import Path

# Ensure Backend root is in sys.path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.main import app
import uvicorn

demo = None
try:
    import gradio as gr

    with gr.Blocks(title="ResQra Emergency Coordination API") as demo:
        gr.Markdown(
            "# 🌊 ResQra Emergency Flood Coordination Backend\n"
            "**Status**: 🟢 Online and Operational for Hackathon Judges\n\n"
            "This service provides the core FastAPI REST and WebSocket endpoints for:\n"
            "- **ResQra Landing Page**\n"
            "- **Judge Simulation Sandbox** (`/api/simulation/...`)\n"
            "- **Tactical Command Console** (`/api/ops/...`, `/ws/ops`)\n\n"
            "API Documentation: [OpenAPI Docs](/docs) | Health Check: [/api/health](/api/health)"
        )

    app = gr.mount_gradio_app(app, demo, path="/")
except Exception as e:
    print(f"[Notice] Gradio UI mount skipped: {e}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    uvicorn.run(app, host="0.0.0.0", port=port)
