# main.py
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase_client import supabase  # あなたの既存のクライアント

app = FastAPI()

# --- CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # 本番はフロントのドメインに
    allow_credentials=True,                   # Cookieを使わないなら False でもOK
    allow_methods=["*"],                      # 必要最低限なら ["POST","GET","OPTIONS"]
    allow_headers=["*"],                      # 必要最低限なら ["Content-Type","Authorization"]
)

# （保険）任意パスのOPTIONSに200を返す
@app.options("/{rest_of_path:path}")
def preflight_handler(rest_of_path: str):
    return {}

# --- ヘルスチェック ---
@app.get("/")
def read_root():
    return {"message": "Hello, World!"}

# --- スキーマ ---
class UserSignUpRequest(BaseModel):
    email: str
    password: str

class UserSignInRequest(BaseModel):
    email: str
    password: str

# --- エンドポイント ---
@app.post("/auth/signup")
def signup(user_request: UserSignUpRequest):
    try:
        resp = supabase.auth.sign_up({
            "email": user_request.email,
            "password": user_request.password,
        })
        if resp.user:
            return {"message": "User signed up successfully. Check your email for confirmation."}
        raise HTTPException(status_code=500, detail="Internal server error.")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/auth/signin")
def signin(user_request: UserSignInRequest):
    try:
        resp = supabase.auth.sign_in_with_password({
            "email": user_request.email,
            "password": user_request.password,
        })
        if resp.session:
            return {
                "message": "User signed in successfully.",
                "access_token": resp.session.access_token,
                "user": resp.user.dict(),
            }
        raise HTTPException(status_code=500, detail="Internal server error.")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))