# app_crystal.py
from typing import Optional
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from supabase_client import supabase_as

router = APIRouter(prefix="/crystals", tags=["crystals"])
auth_scheme = HTTPBearer(auto_error=True)

# ===== Auth helper =====
def get_current_user(creds: HTTPAuthorizationCredentials = Depends(auth_scheme)):
    """
    Authorization: Bearer <access_token> を受け取り、
    Supabaseのユーザー情報を取得。失敗時は401。
    """
    try:
        db = supabase_as(creds.credentials)
        resp = db.auth.get_user(creds.credentials)
        if not resp or not getattr(resp, "user", None):
            raise HTTPException(status_code=401, detail="Unauthenticated")
        return resp.user
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid authentication credentials")

# ===== DTO =====
class CreateCrystalPayload(BaseModel):
    room_id: int
    title: str
    target_value: Decimal = Field(..., max_digits=12, decimal_places=4)
    unit: str

class CrystalRecordCreate(BaseModel):
    value: Decimal = Field(..., max_digits=12, decimal_places=4)
    note: Optional[str] = None

class CrystalSummary(BaseModel):
    crystal_id: int
    title: str
    target_value: Decimal
    unit: str
    total_value: Decimal
    progress_rate: float  # 0.0 ~ 1.0

class CrystalWithRoom(BaseModel):
    crystal_id: int
    room_id: int
    room_name: str
    title: str
    target_value: Decimal
    unit: str

# ===== Utils =====
def _fetch_crystal_by_room(room_id: int, token: str):
    """ルームに紐づく結晶を1件取得（MVP: 1ルーム1結晶想定）"""
    db = supabase_as(token)
    try:
        res = db.table("crystals").select("*").eq("room_id", room_id).limit(1).execute()
        rows = res.data or []
        return rows[0] if rows else None
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB error (crystals by room): {e}")

def _fetch_crystal(crystal_id: int, token: str):
    """crystal_idで結晶を取得（RLSにより見えなければ404相当）"""
    db = supabase_as(token)
    try:
        res = db.table("crystals").select("*").eq("crystal_id", crystal_id).limit(1).execute()
        rows = res.data or []
        if not rows:
            raise HTTPException(status_code=404, detail="crystal not found")
        return rows[0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB error (crystal fetch): {e}")

def _fetch_room_name(room_id: int, token: str) -> Optional[str]:
    """rooms.name を取得"""
    db = supabase_as(token)
    try:
        res = db.table("rooms").select("name").eq("id", room_id).limit(1).execute()
        rows = res.data or []
        return rows[0]["name"] if rows else None
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB error (rooms name): {e}")

def _sum_records(crystal_id: int, token: str) -> Decimal:
    """記録の合計値を計算（必要に応じてRPC化を検討）"""
    db = supabase_as(token)
    try:
        res = db.table("crystal_records").select("value").eq("crystal_id", crystal_id).execute()
        total = Decimal("0")
        for row in (res.data or []):
            total += Decimal(str(row["value"]))
        return total
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB error (records sum): {e}")

# ===== Endpoints =====
@router.post("", summary="結晶を作成（1ルーム1個想定）")
def create_crystal(
    payload: CreateCrystalPayload,
    creds: HTTPAuthorizationCredentials = Depends(auth_scheme),
    user=Depends(get_current_user),
):
    db = supabase_as(creds.credentials)

    existing = _fetch_crystal_by_room(payload.room_id, creds.credentials)
    if existing:
        raise HTTPException(status_code=409, detail="crystal already exists for this room")

    try:
        res = (
            db.table("crystals")
            .insert({
                "room_id": payload.room_id,
                "title": payload.title,
                "target_value": str(payload.target_value),  # numericは文字列で渡す
                "unit": payload.unit,
            })
            .select("*")
            .execute()
        )
        if not res.data:
            raise HTTPException(status_code=400, detail="insert crystal failed")
        return res.data[0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB error (crystal insert): {e}")

@router.get("/by-room/{room_id}", response_model=CrystalWithRoom, summary="ルームの結晶を取得（room_name付き）")
def get_crystal_by_room(
    room_id: int,
    creds: HTTPAuthorizationCredentials = Depends(auth_scheme),
    user=Depends(get_current_user),
):
    crystal = _fetch_crystal_by_room(room_id, creds.credentials)
    if not crystal:
        raise HTTPException(status_code=404, detail="crystal not found")

    room_name = _fetch_room_name(room_id, creds.credentials)
    if not room_name:
        raise HTTPException(status_code=404, detail="room not found or inaccessible")

    return CrystalWithRoom(
        crystal_id=crystal["crystal_id"],
        room_id=room_id,
        room_name=room_name,
        title=crystal["title"],
        target_value=Decimal(str(crystal["target_value"])),
        unit=crystal["unit"],
    )

@router.post("/{crystal_id}/records", summary="進捗を追加（crystal_id 指定）")
def add_record(
    crystal_id: int,
    payload: CrystalRecordCreate,
    creds: HTTPAuthorizationCredentials = Depends(auth_scheme),
    user=Depends(get_current_user),
):
    db = supabase_as(creds.credentials)
    try:
        # 存在/権限チェック
        crystal = _fetch_crystal(crystal_id, creds.credentials)

        res = (
            db.table("crystal_records")
            .insert({
                "crystal_id": crystal_id,
                "user_id": user.id,
                "value": str(payload.value),
                "note": payload.note or None,
            })
            .select("*")
            .execute()
        )
        if not res.data:
            raise HTTPException(status_code=400, detail="insert record failed")

        # 単回の記録値に対する%を返す仕様（フロント要件踏襲）
        row = res.data[0]
        value = Decimal(str(row["value"]))
        target = Decimal(str(crystal["target_value"]))
        percent = int((value / target * 100)) if target > 0 else 0
        return percent
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to add record: {e}")

@router.post("/by-room/{room_id}/records", summary="進捗を追加（room_id 指定）")
def add_record_by_room(
    room_id: int,
    payload: CrystalRecordCreate,
    creds: HTTPAuthorizationCredentials = Depends(auth_scheme),
    user=Depends(get_current_user),
):
    db = supabase_as(creds.credentials)

    # 1) room_id → crystal を取得（RLSでメンバー以外は不可視）
    crystal = _fetch_crystal_by_room(room_id, creds.credentials)
    if not crystal:
        raise HTTPException(status_code=404, detail="crystal not found for this room")
    crystal_id = crystal["crystal_id"]

    try:
        # 2) 記録を追加（user_id は JWT から）
        res = (
            db.table("crystal_records")
            .insert({
                "crystal_id": crystal_id,
                "user_id": user.id,
                "value": str(payload.value),
                "note": payload.note or None,
            })
            .select("*")
            .execute()
        )
        if not res.data:
            raise HTTPException(status_code=400, detail="insert record failed")

        # 3) 直後のサマリーも返す（UI即時更新用）
        total = _sum_records(crystal_id, creds.credentials)
        target = Decimal(str(crystal["target_value"]))
        rate = float(total / target) if target > 0 else 0.0

        return {
            "record": res.data[0],
            "summary": {
                "crystal_id": crystal_id,
                "title": crystal["title"],
                "target_value": target,
                "unit": crystal["unit"],
                "total_value": total,
                "progress_rate": min(rate, 1.0),
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to add record (by room): {e}")

@router.get("/{crystal_id}/summary", response_model=CrystalSummary, summary="結晶サマリーを取得（crystal_id 指定）")
def get_summary(
    crystal_id: int,
    creds: HTTPAuthorizationCredentials = Depends(auth_scheme),
    user=Depends(get_current_user),
):
    crystal = _fetch_crystal(crystal_id, creds.credentials)
    total = _sum_records(crystal_id, creds.credentials)
    target = Decimal(str(crystal["target_value"]))
    rate = float(total / target) if target > 0 else 0.0
    return CrystalSummary(
        crystal_id=crystal["crystal_id"],
        title=crystal["title"],
        target_value=target,
        unit=crystal["unit"],
        total_value=total,
        progress_rate=min(rate, 1.0),
    )

@router.get("/by-room/{room_id}/summary", summary="結晶サマリーを取得（room_id 指定）")
def get_summary_by_room(
    room_id: int,
    creds: HTTPAuthorizationCredentials = Depends(auth_scheme),
    user=Depends(get_current_user),
):
    crystal = _fetch_crystal_by_room(room_id, creds.credentials)
    if not crystal:
        raise HTTPException(status_code=404, detail="crystal not found for this room")

    crystal_id = crystal["crystal_id"]
    total = _sum_records(crystal_id, creds.credentials)
    target = Decimal(str(crystal["target_value"]))
    rate = float(total / target) if target > 0 else 0.0

    return {
        "crystal_id": crystal_id,
        "title": crystal["title"],
        "target_value": target,
        "unit": crystal["unit"],
        "total_value": total,
        "progress_rate": min(rate, 1.0),
    }

@router.get("/{crystal_id}/records", summary="記録一覧（新しい順）")
def list_records(
    crystal_id: int,
    limit: int = 50,
    creds: HTTPAuthorizationCredentials = Depends(auth_scheme),
    user=Depends(get_current_user),
):
    db = supabase_as(creds.credentials)
    # 権限/存在チェック（RLSで見えなければ404相当）
    _ = _fetch_crystal(crystal_id, creds.credentials)

    try:
        res = (
            db.table("crystal_records")
            .select("*")
            .eq("crystal_id", crystal_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return res.data or []
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB error (records list): {e}")