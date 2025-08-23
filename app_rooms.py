# app_rooms.py
from typing import Optional, List
from decimal import Decimal # condecimalの代わりにDecimalをインポート
from datetime import datetime # joined_at の型定義に使用

from fastapi import APIRouter, Depends, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from supabase_client import supabase
import random, string # generate_password関数に使用

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
    avatar_url: Optional[str] = None # アバターURLはオプション
    role: str
    joined_at: datetime

class CreateGroupPayload(BaseModel):
    name: str
    title: str
    target_value: Decimal
    unit: str
    password: Optional[str] = None  # 指定なければサーバ側で自動生成

# ====== Auth helpers ======
bearer_scheme = HTTPBearer(auto_error=True)

def get_access_token(creds: HTTPAuthorizationCredentials = Depends(bearer_scheme)) -> str:
    """
    HTTPBearerからアクセストークンを抽出し、文字列として返します。
    """
    return creds.credentials

def get_current_user(access_token: str = Depends(get_access_token)):
    """
    提供されたアクセストークンを使用して現在のユーザー情報を取得し、検証します。
    無効な場合は401 HTTPExceptionを発生させます。
    """
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
    """
    指定された長さのランダムな英数字パスワードを生成します。
    """
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

# ====== 1) ソロ作成: room + crystal + 自分をメンバー（トランザクション/RPC） ======
@router.post("/solo")
def create_solo_room(payload: CreateSoloPayload, access_token: str = Depends(get_access_token)):
    """
    ソロモードの部屋とクリスタルを作成し、作成者をメンバーとして登録します。
    （RPC機能を使用しているため、Supabase側の設定が必要です）
    """
    try:
        rpc_client = supabase.postgrest
        rpc_client.auth(access_token)

        resp = rpc_client.rpc(
            "create_solo_room_with_crystal", # SupabaseのRPC関数名
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
            # RPCがnameを保存していない場合に備えて更新
            rpc_client.from_("rooms").update({"name": payload.name}).eq("id", room_id).execute()
        except Exception:
            # ここで失敗しても致命的ではないため、ログに記録するのみ
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

        # ← ここを rooms_members に
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

# --- 新しく追加するグループルーム作成API ---
@router.post("/group")
def create_group_room(payload: CreateGroupPayload, access_token: str = Depends(get_access_token)):
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

        # PostgRESTにアクセストークン付与（超重要）
        pg = supabase.postgrest
        pg.auth(access_token)

        password = payload.password or generate_password()

        # 1) rooms 作成（name列がある前提。無い場合は下のupdateを使う）
        res_room = pg.from_("rooms").insert({
            "host_id": user.id,
            "password": password,
            "mode": "group",
            "name": payload.name,  # もしroomsにnameが無いなら次のtry節のupdateへ
        }).execute()
        created = (res_room.data or [None])[0]
        if not created:
            raise HTTPException(status_code=500, detail="Group room insert failed")
        room_id = created["id"]

        # rooms.nameが存在しないスキーマの場合のフォールバック
        try:
            if "name" not in created:
                pg.from_("rooms").update({"name": payload.name}).eq("id", room_id).execute()
        except Exception:
            pass  # name列が無ければ無視

        # 2) hostとしてメンバー登録（重複無視）
        pg.from_("room_members").upsert({
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

# ====== 3) 参加（パスワード検証 + メンバー登録） ======
@router.post("/join")
def join_room(req: JoinRoomRequest, current_user = Depends(get_current_user)):
    """
    ルームIDとパスワードを検証し、ユーザーを部屋のメンバーとして登録します。
    """
    try:
        # 部屋の存在 & パスワード確認
        room_res = supabase.table("rooms").select("id, password, mode").eq("id", req.room_id).single().execute() # modeも取得
        room = room_res.data
        if not room:
            raise HTTPException(status_code=404, detail="Room not found.")

        if room["password"] != req.password:
            raise HTTPException(status_code=401, detail="Invalid password.")

        # ひとり専用ルームのチェック（ソロモードの場合のみ）
        if room["mode"] == "solo":
            existing_members_count_res = supabase.table("room_members").select("user_id").eq("room_id", req.room_id).limit(1).execute()
            if existing_members_count_res.data and len(existing_members_count_res.data) > 0:
                raise HTTPException(status_code=409, detail="This is a solo room and is already occupied.")

        # メンバー登録（重複時は無視 - upsertを使用）
        supabase.table("room_members").upsert({
            "room_id": req.room_id,
            "user_id": current_user.id,
            "role": "member", # 参加者は"member"ロール
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
    """
    特定の部屋の情報を取得します。
    ユーザーがその部屋のメンバーである必要があります。
    """
    try:
        response = supabase.table("rooms").select("*").eq("id", room_id).single().execute()

        if not response.data:
            raise HTTPException(status_code=404, detail="Room not found.")

        # ユーザーがその部屋のメンバーか確認
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
    """
    特定の部屋のメンバーリストとその表示名、アバターURL、ロール、参加日時を取得します。
    """
    try:
        # room_membersとusersを結合してメンバー情報を取得
        # users!inner(...) は、room_membersのuser_idとusersテーブルを内部結合し、
        # 指定したカラム (display_name, avatar_url) を取得します。
        response = (
            supabase.table("room_members")
            .select(
                "user_id, joined_at, role, users!inner(display_name, avatar_url)"
            )
            .eq("room_id", room_id)
            .order("joined_at", desc=False) # 参加日時でソート
            .execute()
        )

        members_list: List[RoomMemberDisplayInfo] = []
        for row in response.data or []:
            user_info = row.get("users")
            # PostgRESTは1対1なら dict、1対多なら list になることがあるので両対応
            if isinstance(user_info, list):
                user_info = user_info[0] if user_info else None

            if user_info:
                members_list.append(
                    RoomMemberDisplayInfo(
                        user_id=row["user_id"],
                        display_name=user_info.get("display_name", ""), # display_nameがなくてもエラーにならないようにデフォルト値設定
                        avatar_url=user_info.get("avatar_url"), # avatar_urlがなくてもエラーにならないようにデフォルト値設定
                        role=row["role"],
                        joined_at=row["joined_at"],
                    )
                )
        
        return members_list

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch room members: {e}")

