# app_rooms.py
from typing import Optional, List
from decimal import Decimal # condecimalの代わりにDecimalをインポート

from fastapi import APIRouter, Depends, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from supabase_client import supabase
import random, string

router = APIRouter(prefix="/rooms", tags=["rooms"])

# ====== Schemas ======
class CreateSoloPayload(BaseModel):
    name: str
    title: str
    target_value: Decimal # condecimalの代わりにDecimalを使用
    unit: str
    password: Optional[str] = None  # Python 3.9 互換

class JoinRoomRequest(BaseModel):
    room_id: int
    password: str

# 部屋メンバーの表示用データモデル
class RoomMemberDisplayInfo(BaseModel):
    user_id: str
    display_name: str
    role: str # 追加
    joined_at: str # 追加

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

# ====== 1) ソロ作成: room + crystal + 自分をメンバー（トランザクション/RPC） ======
@router.post("/solo")
def create_solo_room(payload: CreateSoloPayload, access_token: str = Depends(get_access_token)):
    try:
        rpc_client = supabase.postgrest
        rpc_client.auth(access_token)

        resp = rpc_client.rpc(
            "create_solo_room_with_crystal",
            {
                "p_title": payload.title,
                "p_target": str(payload.target_value),
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

        try:
            rpc_client.from_("rooms").update({"name": payload.name}).eq("id", room_id).execute()
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

# ====== 2) 通常の部屋作成（rooms に1行+自分をhostでメンバー登録） ======
@router.post("")
def create_room(current_user = Depends(get_current_user)):
    try:
        password = generate_password()
        res_room = supabase.table("rooms").insert({
            "host_id": current_user.id,
            "password": password,
            "mode": "solo",
        }).execute()

        created = (res_room.data or [None])[0]
        if not created:
            raise HTTPException(status_code=500, detail="Room insert failed")

        room_id = created["id"]

        supabase.table("room_members").upsert({
            "room_id": room_id,
            "user_id": current_user.id,
            "role": "host",
        }, on_conflict="room_id,user_id").execute()

        return {
            "message": "Room created successfully.",
            "room_id": room_id,
            "password": password,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database operation failed: {e}")

# ====== 3) 参加（パスワード検証 + メンバー登録） ======
@router.post("/join")
def join_room(req: JoinRoomRequest, current_user = Depends(get_current_user)):
    try:
        room_res = supabase.table("rooms").select("*").eq("id", req.room_id).single().execute()
        room = room_res.data
        if not room:
            raise HTTPException(status_code=404, detail="Room not found.")

        if room["password"] != req.password:
            raise HTTPException(status_code=401, detail="Invalid password.")

        supabase.table("room_members").upsert({
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
        
# ====== 4) 特定の部屋情報を取得 ======
@router.get("/{room_id}", response_model=dict)
def get_room_details(room_id: int, current_user = Depends(get_current_user)):
    try:
        response = supabase.table("rooms").select("*").eq("id", room_id).single().execute()

        if not response.data:
            raise HTTPException(status_code=404, detail="Room not found.")

        is_member_res = supabase.table("room_members").select("user_id").eq("room_id", room_id).eq("user_id", current_user.id).execute()
        if not is_member_res.data:
            raise HTTPException(status_code=403, detail="Forbidden: You are not a member of this room.")
        
        room_details = response.data
        return room_details
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ====== 5) 部屋メンバーのリストを取得 ======
@router.get("/{room_id}/members", response_model=List[RoomMemberDisplayInfo])
def get_room_members(room_id: int, current_user = Depends(get_current_user)):
    try:
        response = supabase.table("room_members").select(
            "user_id, joined_at, role, users(display_name)"
        ).eq("room_id", room_id).execute()

        members_list = []
        for member_data in response.data:
            user_info = member_data.pop('users')
            if user_info:
                members_list.append(RoomMemberDisplayInfo(
                    user_id=member_data['user_id'],
                    display_name=user_info['display_name'],
                    role=member_data['role'],
                    joined_at=member_data['joined_at']
                ))
        
        return members_list

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch room members: {e}")
