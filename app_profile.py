# app_profile.py
from typing import Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel, Field
from supabase_client import supabase

router = APIRouter(prefix="/me", tags=["me"])

USERS_TABLE = "users"


# ====== Schemas ======
class ProfileOut(BaseModel):
    display_name: str = Field(..., description="UIに表示する名前")
    avatar_url: Optional[str] = Field(None, description="プロフィール画像URL")
    solo_count: int = 0
    team_count: int = 0
    badge_count: int = 0


class ProfileUpdate(BaseModel):
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None


# ====== Auth ======
def get_user_id_from_bearer(authorization: str = Header(...)) -> str:
    """
    Authorization: Bearer <access_token> からSupabaseユーザーを取得して user_id を返す。
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid Authorization header")

    access_token = authorization.removeprefix("Bearer ").strip()
    try:
        resp = supabase.auth.get_user(access_token)
    except Exception:
        # SDK通信エラーなどは401で返す
        raise HTTPException(status_code=401, detail="Invalid token")

    user = getattr(resp, "user", None)
    if not user or not getattr(user, "id", None):
        raise HTTPException(status_code=401, detail="Invalid token")

    return user.id


# ====== Helpers ======
def _row_to_profile(row: Dict[str, Any]) -> ProfileOut:
    return ProfileOut(
        display_name=row.get("display_name") or "User",
        avatar_url=row.get("avatar_url"),
        solo_count=row.get("solo_count") or 0,
        team_count=row.get("team_count") or 0,
        badge_count=row.get("badge_count") or 0,
    )


def _default_profile_payload(display_name: str = "User") -> Dict[str, Any]:
    return {
        "display_name": display_name,
        "avatar_url": None,
        "solo_count": 0,
        "team_count": 0,
        "badge_count": 0,
    }


# ====== Routes ======
@router.get("/profile", response_model=ProfileOut)
def get_my_profile(user_id: str = Depends(get_user_id_from_bearer)):
    """
    プロフィールを取得。存在しなければデフォルト値で自動作成して返す（フロントが404処理不要）。
    """
    # rows取得（single()は0件でPGRST116になるのでlimit(1)）
    res = (
        supabase.table(USERS_TABLE)
        .select("user_id, display_name, avatar_url, solo_count, team_count, badge_count")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    rows = (res.data or [])
    if rows:
        return _row_to_profile(rows[0])

    # 未作成 → デフォルト作成（ユーザーメタからnameを拾えればそれを初期値に）
    # メタ取得（失敗しても無視）
    try:
        auth = supabase.auth.get_user()
        meta = getattr(getattr(auth, "user", None), "user_metadata", {}) or {}
        initial_name = meta.get("name") or "User"
    except Exception:
        initial_name = "User"

    payload = {"user_id": user_id, **_default_profile_payload(initial_name)}
    supabase.table(USERS_TABLE).insert(payload).execute()

    return _row_to_profile(payload)


@router.patch("/profile", response_model=ProfileOut)
def update_my_profile(
    payload: ProfileUpdate, user_id: str = Depends(get_user_id_from_bearer)
):
    """
    display_name / avatar_url を更新。存在しなければ先にデフォルト作成してから更新結果を返す。
    """
    # まず存在確認
    res0 = (
        supabase.table(USERS_TABLE)
        .select("user_id")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    exists = bool(res0.data)

    if not exists:
        # デフォルト作成
        supabase.table(USERS_TABLE).insert({"user_id": user_id, **_default_profile_payload()}).execute()

    update_fields: Dict[str, Any] = {}
    if payload.display_name is not None:
        update_fields["display_name"] = payload.display_name
    if payload.avatar_url is not None:
        update_fields["avatar_url"] = payload.avatar_url

    if not update_fields:
        # 空パッチは400
        raise HTTPException(status_code=400, detail="No fields to update")

    supabase.table(USERS_TABLE).update(update_fields).eq("user_id", user_id).execute()

    # 更新後の行を返す
    res = (
        supabase.table(USERS_TABLE)
        .select("display_name, avatar_url, solo_count, team_count, badge_count")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    if not rows:
        # ここに来ることはほぼ無いが保険
        raise HTTPException(status_code=404, detail="Profile not found after update")

    return _row_to_profile(rows[0])