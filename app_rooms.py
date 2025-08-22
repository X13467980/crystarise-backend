# app_rooms.py
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel, condecimal
from supabase_client import supabase  # anonキーのクライアントを想定

router = APIRouter(prefix="/rooms", tags=["rooms"])

class CreateSoloPayload(BaseModel):
    title: str
    target_value: condecimal(max_digits=12, decimal_places=4)
    unit: str
    password: str | None = None

def require_auth(authorization: str = Header(...)):
    # "Bearer <token>" を想定
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    return authorization.split(" ", 1)[1]

@router.post("/solo")
def create_solo_room(payload: CreateSoloPayload, access_token: str = Depends(require_auth)):
    try:
        # RPCは "Authorization: Bearer <token>" を付けて呼ぶ必要がある
        # supabase-pyは個別リクエストヘッダを指定しづらいので、postgrestへ直接叩くか、
        # もしくは supabase.postgrest.auth(access_token) を使う（最新版で利用可）。
        # ここでは postgrest の auth ヘルパを使う例:
        rpc_client = supabase.postgrest
        rpc_client.auth(access_token)

        resp = rpc_client.rpc(
            "create_solo_room_with_crystal",
            {
                "p_title": payload.title,
                "p_target": str(payload.target_value),  # numericは文字列で安全
                "p_unit": payload.unit,
                "p_password": payload.password,
            },
        ).execute()

        if not resp.data or len(resp.data) == 0:
            raise HTTPException(status_code=500, detail="RPC returned no data")

        row = resp.data[0]
        return {
            "room_id": row["room_id"],
            "crystal_id": row["crystal_id"],
            "title": payload.title,
            "target_value": str(payload.target_value),
            "unit": payload.unit,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create solo room: {e}")