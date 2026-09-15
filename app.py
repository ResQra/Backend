import os
import uvicorn
from app.main import app as fastapi_app

# In Hugging Face Gradio Space, gradio is pre-installed.
# We mount a lightweight status page at /status while preserving all FastAPI routes.
try:
    import gradio as gr

    with gr.Blocks(title="ResQra API") as demo:
        gr.Markdown("# 🌊 ResQra Disaster Response Backend")
        gr.Markdown(
            "FastAPI REST endpoints, WebSockets, and Multi-Agent Triage are active.\n\n"
            "- **API Health**: [/api/health](/api/health)\n"
            "- **Swagger Docs**: [/docs](/docs)\n"
            "- **Ops WebSocket**: `/ws/ops`"
        )
    app = gr.mount_gradio_app(fastapi_app, demo, path="/status")
except Exception:
    app = fastapi_app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    uvicorn.run(app, host="0.0.0.0", port=port)
