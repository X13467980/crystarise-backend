# app_rooms.py
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, condecimal
from supabase_client import supabase
import random, string

router = APIRouter(prefix="/rooms", tags=["rooms"])

# ====== Schemas ======
class CreateSoloPayload(BaseModel):
    title: str
    target_value: condecimal(max_digits=12, decimal_places=4)
    unit: str
    password: Optional[str] = None  # Python 3.9 互換

class JoinRoomRequest(BaseModel):
    room_id: int
    password: str

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
        # RLS を効かせるため、呼び出し時にユーザーのトークンを付与
        rpc_client = supabase.postgrest
        rpc_client.auth(access_token)

        resp = rpc_client.rpc(
            "create_solo_room_with_crystal",
            {
                "p_title": payload.title,
                "p_target": str(payload.target_value),  # numeric は文字列で安全
                "p_unit": payload.unit,
                "p_password": payload.password,
            },
        ).execute()

        data = resp.data or []
        if not data:
            raise HTTPException(status_code=500, detail="RPC returned no data")

        row = data[0]
        # v1: room_id / crystal_id, v2: room_id_out / crystal_id_out に両対応
        room_id = row.get("room_id_out") or row.get("room_id")
        crystal_id = row.get("crystal_id_out") or row.get("crystal_id")

        if room_id is None or crystal_id is None:
            # デバッグ用に生データを見たいときはログを仕込むと良い
            raise HTTPException(status_code=500, detail=f"Unexpected RPC payload keys: {list(row.keys())}")

        return {
            "room_id": room_id,
            "crystal_id": crystal_id,
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
            "mode": "solo",  # 必要に応じて変更（teamにしたい場合など）
        }).execute()

        created = (res_room.data or [None])[0]
        if not created:
            raise HTTPException(status_code=500, detail="Room insert failed")

        room_id = created["id"]

        # 作成者を host でメンバー登録（重複時は無視）
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
        # 部屋の存在 & パスワード確認
        room_res = supabase.table("rooms").select("*").eq("id", req.room_id).single().execute()
        room = room_res.data
        if not room:
            raise HTTPException(status_code=404, detail="Room not found.")

        if room["password"] != req.password:
            raise HTTPException(status_code=401, detail="Invalid password.")

        # 正しい場合はメンバー登録（重複時は無視）
        supabase.table("room_members").upsert({
            "room_id": req.room_id,
            "user_id": current_user.id,
            "role": "member",
        }, on_conflict="room_id,user_id").execute()

        return {"message": "Successfully joined the room."}
    except HTTPException:
        raise
    except Exception as e:
        # PostgREST の "row not found" 表現にも配慮
        if "rows not found" in str(e):
            raise HTTPException(status_code=404, detail="Room not found.")
        raise HTTPException(status_code=500, detail=str(e))