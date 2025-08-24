# app_rooms.py
from typing import Optional, List
from decimal import Decimal
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from supabase_client import supabase
import random, string  # generate_password に使用

router = APIRouter(prefix="/rooms", tags=["rooms"])

# ====== Schemas ======
class CreateSoloPayload(BaseModel):
    name: str
    title: str
    target_value: Decimal
    unit: str
    password: Optional[str] = None

class JoinRoomRequest(BaseModel):
    room_id: int
    password: str

class RoomMemberDisplayInfo(BaseModel):
    user_id: str
    display_name: str
    avatar_url: Optional[str] = None
    role: str
    joined_at: datetime

class RoomBrief(BaseModel):
    id: int
    name: str

class CreateGroupPayload(BaseModel):
    name: str
    title: str
    target_value: Decimal
    unit: str
    password: Optional[str] = None  # 指定なければサーバ側で自動生成

# ====== Auth helpers ======
bearer_scheme = HTTPBearer(auto_error=True)

def get_access_token(creds: HTTPAuthorizationCredentials = Depends(bearer_scheme)) -> str:
    return creds.credentials

def get_current_user(access_token: str = Depends(get_access_token)):
    try:
        resp = supabase.auth.get_user(access_token)
        user = getattr(resp, "user", None)
        if not user or not getattr(user, "id", None):
            raise HTTPException(status_code=401, detail="Invalid authentication credentials")
        return user
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid authentication credentials")

# ====== Utils ======
def generate_password(length: int = 6) -> str:
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

# ====== 1) ソロ作成: room + crystal + 自分をメンバー（RPC） ======
@router.post("/solo")
def create_solo_room(
    payload: CreateSoloPayload,
    access_token: str = Depends(get_access_token),
):
    try:
        pg = supabase.postgrest
        pg.auth(access_token)

        resp = pg.rpc(
            "create_solo_room_with_crystal",
            {
                "p_title": payload.title,
                "p_target": str(payload.target_value),  # numeric は文字列で
                "p_unit": payload.unit,
                "p_password": payload.password,
                "p_name": payload.name,
            },
        ).execute()

        data = resp.data or []
        if not data:
            raise HTTPException(status_code=500, detail="RPC returned no data")

        row = data[0]
        room_id = row.get("room_id_out") or row.get("room_id")
        crystal_id = row.get("crystal_id_out") or row.get("crystal_id")
        if room_id is None or crystal_id is None:
            raise HTTPException(status_code=500, detail=f"Unexpected RPC payload keys: {list(row.keys())}")

        # rooms.name を念のため更新（無いスキーマでも try/except）
        try:
            pg.from_("rooms").update({"name": payload.name}).eq("id", room_id).execute()
        except Exception:
            pass

        return {
            "room_id": room_id,
            "crystal_id": crystal_id,
            "name": payload.name,
            "title": payload.title,
            "target_value": str(payload.target_value),
            "unit": payload.unit,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create solo room: {e}")

# ====== 2) 通常の部屋作成（rooms + 自分をhostでメンバー登録） ======
@router.post("")
def create_room(
    current_user = Depends(get_current_user),
    access_token: str = Depends(get_access_token),
):
    try:
        pg = supabase.postgrest
        pg.auth(access_token)

        password = generate_password()
        res_room = pg.from_("rooms").insert({
            "host_id": current_user.id,
            "password": password,
            "mode": "solo",
        }).select("*").execute()

        created = (res_room.data or [None])[0]
        if not created:
            raise HTTPException(status_code=500, detail="Room insert failed")

        room_id = created["id"]

        # rooms_members に upsert（重複時は無視）
        pg.from_("rooms_members").upsert({
            "room_id": room_id,
            "user_id": current_user.id,
            "role": "host",
        }, on_conflict="room_id,user_id").execute()

        return {"message": "Room created successfully.", "room_id": room_id, "password": password}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database operation failed: {e}")

# --- 3) グループルーム作成 ---
@router.post("/group")
def create_group_room(
    payload: CreateGroupPayload,
    access_token: str = Depends(get_access_token),
):
    """グループモードの部屋を作成し、作成者をホストとしてメンバー登録。結晶も作成。"""
    try:
        # 現在ユーザー
        resp = supabase.auth.get_user(access_token)
        user = getattr(resp, "user", None)
        if not user or not getattr(user, "id", None):
            raise HTTPException(status_code=401, detail="Invalid authentication credentials")

        pg = supabase.postgrest
        pg.auth(access_token)

        password = payload.password or generate_password()

        # rooms 作成
        res_room = pg.from_("rooms").insert({
            "host_id": user.id,
            "password": password,
            "mode": "group",
            "name": payload.name,
        }).select("*").execute()

        created = (res_room.data or [None])[0]
        if not created:
            raise HTTPException(status_code=500, detail="Group room insert failed")
        room_id = created["id"]

        # name フォールバック
        try:
            if "name" not in created:
                pg.from_("rooms").update({"name": payload.name}).eq("id", room_id).execute()
        except Exception:
            pass

        # host としてメンバー登録
        pg.from_("rooms_members").upsert({
            "room_id": room_id,
            "user_id": user.id,
            "role": "host",
        }, on_conflict="room_id,user_id").execute()

        # crystals 作成
        pg.from_("crystals").insert({
            "room_id": room_id,
            "title": payload.title,
            "target_value": str(payload.target_value),
            "unit": payload.unit,
        }).execute()

        return {
            "message": "Group room & crystal created successfully.",
            "room_id": room_id,
            "password": password,
            "crystal": {
                "title": payload.title,
                "target_value": str(payload.target_value),
                "unit": payload.unit,
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create group room with crystal: {e}")

# ====== 4) 参加（パスワード検証 + メンバー登録） ======
@router.post("/join")
def join_room(
    req: JoinRoomRequest,
    current_user = Depends(get_current_user),
    access_token: str = Depends(get_access_token),
):
    try:
        pg = supabase.postgrest
        pg.auth(access_token)

        room_res = pg.from_("rooms").select("id,password,mode").eq("id", req.room_id).limit(1).execute()
        room_rows = room_res.data or []
        room = room_rows[0] if room_rows else None
        if not room:
            raise HTTPException(status_code=404, detail="Room not found.")
        if room["password"] != req.password:
            raise HTTPException(status_code=401, detail="Invalid password.")

        # ソロは1人のみ
        if room["mode"] == "solo":
            exists_res = pg.from_("rooms_members").select("user_id").eq("room_id", req.room_id).limit(1).execute()
            if exists_res.data and len(exists_res.data) > 0:
                raise HTTPException(status_code=409, detail="This is a solo room and is already occupied.")

        pg.from_("rooms_members").upsert({
            "room_id": req.room_id,
            "user_id": current_user.id,
            "role": "member",
        }, on_conflict="room_id,user_id").execute()

        return {"message": "Successfully joined the room."}
    except HTTPException:
        raise
    except Exception as e:
        if "rows not found" in str(e):
            raise HTTPException(status_code=404, detail="Room not found.")
        raise HTTPException(status_code=500, detail=str(e))

# ====== 5) 自分の所属ルーム一覧（id, name） ← 静的パスを先に置く／アプリ側で降順ソート
@router.get("/mine", response_model=List[RoomBrief], summary="自分の所属ルーム一覧（id,name）")
def list_my_rooms(
    current_user = Depends(get_current_user),
    access_token: str = Depends(get_access_token),
):
    """
    rooms_members から自分の room_id を取り出し、rooms の id/name を返す。
    joined_at は Python 側で降順ソート（PostgREST の order パース不具合を回避）。
    """
    try:
        pg = supabase.postgrest
        pg.auth(access_token)

        # 1) 自分の membership を取得（DBでは order しない）
        mem = pg.from_("rooms_members").select("room_id, joined_at").eq("user_id", current_user.id).execute()
        rows = mem.data or []

        # joined_at 降順（新しい順）に整列
        rows.sort(key=lambda r: r.get("joined_at") or "", reverse=True)

        # 重複排除しつつ順序維持
        room_ids: list[int] = []
        seen = set()
        for r in rows:
            rid = r["room_id"]
            if rid not in seen:
                seen.add(rid)
                room_ids.append(rid)

        if not room_ids:
            return []

        # 2) rooms から id/name を一括取得
        rms = pg.from_("rooms").select("id,name").in_("id", room_ids).execute()
        items = rms.data or []

        # membership順に並べ替え
        order = {rid: i for i, rid in enumerate(room_ids)}
        items.sort(key=lambda x: order.get(x["id"], 10**9))

        return [{"id": it["id"], "name": it.get("name", "") or ""} for it in items]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB error: {e}")

# ====== 6) 特定の部屋情報を取得（動的パスは最後に）
@router.get("/{room_id}", response_model=dict)
def get_room_details(
    room_id: int,
    current_user = Depends(get_current_user),
    access_token: str = Depends(get_access_token),
):
    try:
        pg = supabase.postgrest
        pg.auth(access_token)

        response = pg.from_("rooms").select("*").eq("id", room_id).limit(1).execute()
        room = (response.data or [None])[0]
        if not room:
            raise HTTPException(status_code=404, detail="Room not found.")

        is_member_res = pg.from_("rooms_members").select("user_id").eq("room_id", room_id).eq("user_id", current_user.id).limit(1).execute()
        if not (is_member_res.data and len(is_member_res.data) > 0):
            raise HTTPException(status_code=403, detail="Forbidden: You are not a member of this room.")

        return room
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ====== 7) 部屋メンバーのリストを取得（Python 側で joined_at 昇順ソート）
@router.get("/{room_id}/members", response_model=List[RoomMemberDisplayInfo])
def get_room_members(
    room_id: int,
    current_user = Depends(get_current_user),
    access_token: str = Depends(get_access_token),
):
    try:
        pg = supabase.postgrest
        pg.auth(access_token)

        res = (
            pg.from_("rooms_members")
            .select("user_id, joined_at, role, users!inner(display_name, avatar_url)")
            .eq("room_id", room_id)
            .execute()
        )
        rows = res.data or []

        # joined_at 昇順（古い順）に整列
        rows.sort(key=lambda r: r.get("joined_at") or "")

        members_list: List[RoomMemberDisplayInfo] = []
        for m in rows:
            user_info = m.get("users")
            if isinstance(user_info, list):
                user_info = user_info[0] if user_info else None
            user_info = user_info or {}
            members_list.append(
                RoomMemberDisplayInfo(
                    user_id=m["user_id"],
                    display_name=user_info.get("display_name", ""),
                    avatar_url=user_info.get("avatar_url"),
                    role=m["role"],
                    joined_at=m["joined_at"],
                )
            )
        return members_list

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch room members: {e}")
