# supabase_client.py
import os
from supabase import create_client, Client

# 追加：.env を読む（python-dotenv）
try:
    from dotenv import load_dotenv
    load_dotenv()  # プロジェクトルートの .env を自動読込
except Exception:
    pass  # 未インストールでも動くが、環境変数は自力で設定が必要

# NEXT_PUBLIC_* にもフォールバック（フロント共有の値を流用できる）
SUPABASE_URL = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY") or os.getenv("NEXT_PUBLIC_SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_URL / SUPABASE_KEY が環境変数に設定されていません。")

# 匿名クライアント
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def supabase_as(access_token: str) -> Client:
    """ユーザーJWTでRLSを通すクライアント"""
    client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    try:
        client.postgrest.auth(access_token)
    except Exception:
        pass
    try:
        client.storage.client.headers.update({"Authorization": f"Bearer {access_token}"})
    except Exception:
        pass
    try:
        client.realtime.set_auth(access_token)
    except Exception:
        pass
    return client
