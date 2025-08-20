# app_profile.py
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel
from typing import Optional
from supabase_client import supabase

router = APIRouter(prefix="/me", tags=["me"])

class ProfileOut(BaseModel):
    display_name: str
    avatar_url: Optional[str] = None
    solo_count: int
    team_count: int
    badge_count: int

class ProfileUpdate(BaseModel):
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None

def get_user_id_from_bearer(authorization: str = Header(...)) -> str:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid Authorization header")
    access_token = authorization.removeprefix("Bearer ").strip()
    user = supabase.auth.get_user(access_token)
    if not user or not user.user:
        raise HTTPException(status_code=401, detail="Invalid token")
    return user.user.id

@router.get("/profile", response_model=ProfileOut)
def get_my_profile(user_id: str = Depends(get_user_id_from_bearer)):
    # ← single()だと0件時にPGRST116になるのでlimit(1)で安全に取る
    res = supabase.table("users").select(
        "display_name, avatar_url, solo_count, team_count, badge_count"
    ).eq("user_id", user_id).limit(1).execute()

    rows = res.data or []
    if not rows:
        # ここで404を返す（未作成）
        raise HTTPException(status_code=404, detail="Profile not found")
    return rows[0]

@router.patch("/profile", response_model=ProfileOut)
def update_my_profile(payload: ProfileUpdate, user_id: str = Depends(get_user_id_from_bearer)):
    update_fields = {}
    if payload.display_name is not None:
        update_fields["display_name"] = payload.display_name
    if payload.avatar_url is not None:
        update_fields["avatar_url"] = payload.avatar_url

    if not update_fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    # update → limit(1) で返す
    supabase.table("users").update(update_fields).eq("user_id", user_id).execute()
    res = supabase.table("users").select(
        "display_name, avatar_url, solo_count, team_count, badge_count"
    ).eq("user_id", user_id).limit(1).execute()

    rows = res.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Profile not found after update")
    return rows[0]