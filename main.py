# main.py
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase_client import supabase

# Sub-routers
from app_profile import router as me_router
from app_rooms import router as rooms_router
from app_crystal import router as crystals_router  # ← 追加
from starlette.status import HTTP_400_BAD_REQUEST, HTTP_500_INTERNAL_SERVER_ERROR

app = FastAPI(
    title="CrystaRise API",
    version="1.0.0",
)

# ===== CORS =====
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # 必要に応じてフロントのURLを追加
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===== Preflight for any path =====
@app.options("/{rest_of_path:path}")
def preflight_handler(rest_of_path: str):
    return {}

# ===== Health =====
@app.get("/")
def health():
    return {"ok": True, "message": "Hello, World!"}

# ===== Include sub-routers =====
# /me/* エンドポイント
app.include_router(me_router)
# /rooms/* エンドポイント（solo作成・参加などを集約）
app.include_router(rooms_router)
# /crystals/* エンドポイント（結晶の作成・記録・集計）
app.include_router(crystals_router)  # ← 追加

# ===== Auth DTO & Room Join DTO =====
class UserSignUpRequest(BaseModel):
    email: str
    password: str

class UserSignInRequest(BaseModel):
    email: str
    password: str

class JoinRoomRequest(BaseModel):
    room_id: str
    password: str

# ===== Auth endpoints =====
@app.post("/auth/signup", tags=["auth"])
def signup(user_request: UserSignUpRequest):
    try:
        resp = supabase.auth.sign_up({
            "email": user_request.email,
            "password": user_request.password,
        })
        if getattr(resp, "user", None):
            return {"message": "User signed up successfully. Check your email for confirmation."}
        raise HTTPException(status_code=HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error.")
    except Exception as e:
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=str(e))

@app.post("/auth/signin", tags=["auth"])
def signin(user_request: UserSignInRequest):
    try:
        resp = supabase.auth.sign_in_with_password({
            "email": user_request.email,
            "password": user_request.password,
        })
        if getattr(resp, "session", None):
            user_obj = getattr(resp, "user", None)
            user_payload = None
            if user_obj:
                user_payload = {
                    "id": getattr(user_obj, "id", None),
                    "email": getattr(user_obj, "email", None),
                    "user_metadata": getattr(user_obj, "user_metadata", None),
                }
            return {
                "message": "User signed in successfully.",
                "access_token": resp.session.access_token,
                "user": user_payload,
            }
        raise HTTPException(status_code=HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error.")
    except Exception as e:
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=str(e))
