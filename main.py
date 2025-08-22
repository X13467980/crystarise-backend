# main.py
from fastapi import FastAPI, HTTPException, Depends, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from supabase_client import supabase
from app_profile import router as me_router
import random
import string

app = FastAPI(
    title="CrystaRise API",
    version="1.0.0"
)

# ===== CORS =====
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===== Preflight for any path =====
@app.options("/{rest_of_path:path}")
def preflight_handler(rest_of_path: str):
    return {}

# ===== Include sub-routers =====
# ※ /me/profile を提供
app.include_router(me_router)

# ===== Health =====
@app.get("/")
def read_root():
    return {"message": "Hello, World!"}

# ===== Auth DTO =====
class UserSignUpRequest(BaseModel):
    email: str
    password: str

class UserSignInRequest(BaseModel):
    email: str
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
        raise HTTPException(status_code=500, detail="Internal server error.")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

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
                # supabase-py v2 の user は属性アクセス可能
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
        raise HTTPException(status_code=500, detail="Internal server error.")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# ===== Security: current user from Bearer =====
bearer_scheme = HTTPBearer(auto_error=True)

def get_current_user(creds: HTTPAuthorizationCredentials = Security(bearer_scheme)):
    """
    Swagger の Authorize（鍵アイコン）に Bearer <token> を入れると、
    ここに自動で渡ってきます。
    """
    try:
        user_info = supabase.auth.get_user(creds.credentials)
        user = getattr(user_info, "user", None)
        if not user or not getattr(user, "id", None):
            raise HTTPException(status_code=401, detail="Invalid authentication credentials")
        return user
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid authentication credentials")

# ===== Rooms =====
def generate_password(length: int = 6):
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

@app.post("/rooms", tags=["rooms"])
def create_room(current_user = Depends(get_current_user)):
    try:
        password = generate_password()
        response = supabase.table("rooms").insert({
            "host_id": current_user.id,
            "password": password
        }).execute()
        created_room = response.data[0] if response.data else None
        return {
            "message": "Room created successfully.",
            "room_id": created_room["id"] if created_room else None,
            "password": password
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database operation failed: {e}")