from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import DB_PATH

from routers.auth_router import router as auth_router
from routers.profile_router import router as profile_router
from routers.post_router import router as post_router
from routers.network_router import router as network_router
from routers.message_router import router as message_router
from routers.gig_router import router as gig_router
from routers.notification_router import router as notification_router
from routers.post_chat_router import router as post_chat_router
from routers.location_router import router as location_router




app = FastAPI(
    title="ConnectNow Unified API",
    description="One backend for ConnectNow auth, profile, posts, network, messages, gigs and notifications.",
    version="1.0.0"
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "service": "ConnectNow Unified API"
    }


app.include_router(auth_router)
app.include_router(profile_router)
app.include_router(post_router)
app.include_router(network_router)
app.include_router(message_router)
app.include_router(gig_router)
app.include_router(notification_router)
app.include_router(post_chat_router)
app.include_router(location_router)
