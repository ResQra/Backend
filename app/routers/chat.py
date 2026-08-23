from fastapi import APIRouter, Depends, HTTPException

from app.agents_gateway import gateway, llm, memory
from app.auth.deps import CurrentUser, get_current_user
from app.db.repos import chat
from app.models import ChatMessageOut, ChatRequest

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("")
async def send_message(body: ChatRequest, user: CurrentUser = Depends(get_current_user)):
    """F18: resident ↔ ResidentAgent. Router owns persistence: DynamoDB when
    available, in-memory fallback otherwise — the agent always gets context.
    SSE streaming upgrade comes later — response shape stays compatible."""
    try:
        history = chat.get_history(user.id)
    except Exception:
        history = memory.get_history(user.id)

    for store in (chat, memory):
        try:
            store.append_message(user.id, "user", body.message)
        except Exception:
            pass

    try:
        reply = await gateway.resident_chat(user.id, body.message, history)
    except llm.LLMNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except gateway.AgentNotConnectedError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    for store in (chat, memory):
        try:
            store.append_message(user.id, "agent", reply)
        except Exception:
            pass
    return {"reply": reply}


@router.get("/history", response_model=list[ChatMessageOut])
def history(user: CurrentUser = Depends(get_current_user)):
    return chat.get_history(user.id)
