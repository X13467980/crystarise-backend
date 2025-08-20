# main.py
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase_client import supabase
from app_profile import router as me_router

app = FastAPI()

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 任意パスのOPTIONSに200
@app.options("/{rest_of_path:path}")
def preflight_handler(rest_of_path: str):
    return {}

# ここを追加！
app.include_router(me_router)

@app.get("/")
def read_root():
    return {"message": "Hello, World!"}

class UserSignUpRequest(BaseModel):
    email: str
    password: str

class UserSignInRequest(BaseModel):
    email: str
    password: str

@app.post("/auth/signup")
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

@app.post("/auth/signin")
def signin(user_request: UserSignInRequest):
    try:
        resp = supabase.auth.sign_in_with_password({
            "email": user_request.email,
            "password": user_request.password,
        })
        if getattr(resp, "session", None):
            return {
                "message": "User signed in successfully.",
                "access_token": resp.session.access_token,
                "user": resp.user.dict() if getattr(resp, "user", None) else None,
            }
        raise HTTPException(status_code=500, detail="Internal server error.")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))