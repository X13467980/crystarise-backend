# app_profile.py（例）
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel
from supabase_client import supabase  # あなたの既存クライアント

router = APIRouter(prefix="/me", tags=["me"])

class ProfileOut(BaseModel):
    display_name: str
    avatar_url: str | None = None
    solo_count: int
    team_count: int
    badge_count: int

class ProfileUpdate(BaseModel):
    display_name: str | None = None
    avatar_url: str | None = None

def get_user_id_from_bearer(authorization: str = Header(...)) -> str:
    # "Bearer <token>" を想定。検証を簡略化（本番はJWT検証やSupabaseのauthヘルパーを使う）
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid Authorization header")
    access_token = authorization.removeprefix("Bearer ").strip()

    # Supabaseのget_user()などでtoken→user情報取得（Python SDK v2系はauth.get_user()）
    user = supabase.auth.get_user(access_token)
    if not user or not user.user:
        raise HTTPException(status_code=401, detail="Invalid token")
    return user.user.id

@router.get("/profile", response_model=ProfileOut)
def get_my_profile(user_id: str = Depends(get_user_id_from_bearer)):
    res = supabase.table("users").select(
        "display_name, avatar_url, solo_count, team_count, badge_count"
    ).eq("user_id", user_id).single().execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Profile not found")
    return res.data

@router.patch("/profile", response_model=ProfileOut)
def update_my_profile(payload: ProfileUpdate, user_id: str = Depends(get_user_id_from_bearer)):
    update_fields = {}
    if payload.display_name is not None:
        update_fields["display_name"] = payload.display_name
    if payload.avatar_url is not None:
        update_fields["avatar_url"] = payload.avatar_url

    if not update_fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    res = supabase.table("users").update(update_fields).eq("user_id", user_id).select(
        "display_name, avatar_url, solo_count, team_count, badge_count"
    ).single().execute()
    return res.data