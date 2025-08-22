# app_profile.py
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from supabase_client import supabase

router = APIRouter(prefix="/me", tags=["me"])
auth_scheme = HTTPBearer(auto_error=True)

def get_current_user(creds: HTTPAuthorizationCredentials = Depends(auth_scheme)):
    try:
        resp = supabase.auth.get_user(creds.credentials)
        return resp.user
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid authentication credentials")

@router.get("/profile")
def get_profile(user = Depends(get_current_user)):
    # Supabaseのユーザーメタデータ（nameやavatar_url）があれば使い、無ければフォールバック
    meta = getattr(user, "user_metadata", {}) or {}
    display_name = meta.get("name") or (user.email.split("@")[0] if getattr(user, "email", None) else "User")
    avatar_url = meta.get("avatar_url") or ""

    # 進捗系は未実装なら0で返す（必要ならRPCやテーブル集計に置き換えてください）
    solo_count = 0
    team_count = 0
    badge_count = 0

    return {
        "display_name": display_name,
        "avatar_url": avatar_url,
        "solo_count": solo_count,
        "team_count": team_count,
        "badge_count": badge_count,
    }