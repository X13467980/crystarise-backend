# app_rooms.py
from typing import Optional, List
from decimal import Decimal
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
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

        # rooms.name 列が存在しなかった場合でも安全にフォールバック
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
        }).execute()

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
    """
    グループモードの部屋を作成し、作成者をホストとしてメンバー登録。
    さらに、この部屋用の結晶（目標）を作成します。
    """
    try:
        # 現在ユーザー特定（RLS通過にも利用）
        resp = supabase.auth.get_user(access_token)
        user = getattr(resp, "user", None)
        if not user or not getattr(user, "id", None):
            raise HTTPException(status_code=401, detail="Invalid authentication credentials")

        # PostgREST にアクセストークン付与（重要）
        pg = supabase.postgrest
        pg.auth(access_token)

        password = payload.password or generate_password()

        # 1) rooms 作成（name列が無いスキーマでも後でupdate試行）
        res_room = pg.from_("rooms").insert({
            "host_id": user.id,
            "password": password,
            "mode": "group",
            "name": payload.name,
        }).execute()

        created = (res_room.data or [None])[0]
        if not created:
            raise HTTPException(status_code=500, detail="Group room insert failed")
        room_id = created["id"]

        # rooms.name が無い環境向けフォールバック
        try:
            if "name" not in created:
                pg.from_("rooms").update({"name": payload.name}).eq("id", room_id).execute()
        except Exception:
            pass

        # 2) host としてメンバー登録（重複無視）
        pg.from_("rooms_members").upsert({
            "room_id": room_id,
            "user_id": user.id,
            "role": "host",
        }, on_conflict="room_id,user_id").execute()

        # 3) crystals 作成（目標保存）
        pg.from_("crystals").insert({
            "room_id": room_id,
            "title": payload.title,
            "target_value": str(payload.target_value),  # Decimal→strでnumeric(12,4)へ
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

        # .single() はバージョン差で例外になることがあるため limit(1) に統一
        room_res = pg.from_("rooms").select("id,password,mode").eq("id", req.room_id).limit(1).execute()
        room_rows = room_res.data or []
        room = room_rows[0] if room_rows else None
        if not room:
            raise HTTPException(status_code=404, detail="Room not found.")
        if room["password"] != req.password:
            raise HTTPException(status_code=401, detail="Invalid password.")

        # ソロルームは1人のみ
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

# ====== 5) 自分の所属ルーム一覧（id, name） ← ★静的パスを先に置く
@router.get("/mine", response_model=List[RoomBrief], summary="自分の所属ルーム一覧（id,name）")
def list_my_rooms(
    current_user = Depends(get_current_user),
    access_token: str = Depends(get_access_token),
):
    """
    rooms_members から自分の room_id を取り出し、rooms の id/name を返す。
    joined_at があれば参加順で並べ替え。
    """
    try:
        pg = supabase.postgrest
        pg.auth(access_token)

        mem = (
            pg.from_("rooms")
            .select("id,name, rooms_members!inner(user_id, joined_at)")
            .eq("rooms_members.user_id", current_user.id)
            .order("rooms_members.joined_at", desc=True)
            .execute()
        )
        rows = mem.data or []

        # rows は rooms と join 済みなので、そのまま返せるが順序安定化のため一応整形
        results: List[RoomBrief] = []
        for r in rows:
            results.append(RoomBrief(id=r["id"], name=r.get("name", "") or ""))
        return results
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

# ====== 7) 部屋メンバーのリストを取得
@router.get("/{room_id}/members", response_model=List[RoomMemberDisplayInfo])
def get_room_members(
    room_id: int,
    current_user = Depends(get_current_user),
    access_token: str = Depends(get_access_token),
):
    try:
        pg = supabase.postgrest
        pg.auth(access_token)

        response = (
            pg.from_("rooms")
            .select("rooms_members!inner(user_id, joined_at, role, users(display_name,avatar_url))")
            .eq("id", room_id)
            .execute()
        )

        members_list: List[RoomMemberDisplayInfo] = []
        # レコード構造は { rooms_members: [ { user_id, joined_at, role, users: {...} } , ...] }
        rows = response.data or []
        if rows:
            for row in rows:
                for m in row.get("rooms_members", []) or []:
                    user_info = m.get("users") or {}
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