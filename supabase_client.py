# supabase_client.py
import os
from supabase import create_client, Client

# --- .env 読み込み（python-dotenv が無くても動くように） ---
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    pass  # 未インストールでもOK。環境変数は別途設定しておくこと

# NEXT_PUBLIC_* にもフォールバック（フロント共有の値を流用）
SUPABASE_URL = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY") or os.getenv("NEXT_PUBLIC_SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_URL / SUPABASE_KEY が環境変数に設定されていません。(.env も可)")

# 匿名クライアント（RLS非通過の読み取りなどに使用）
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def supabase_as(access_token: str) -> Client:
    """
    指定したユーザーJWTでRLSを通すためのクライアントを作成。
    - PostgREST: auth(token)
    - Storage/Realtime: 可能であればAuthorizationヘッダ等を付与（SDK差異を考慮してbest-effort）
    """
    client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    # PostgREST (必須)
    try:
        client.postgrest.auth(access_token)
    except Exception:
        # SDKの差異で失敗する場合は上位で401等の扱いに
        pass

    # Storage (任意・SDK差異あり)
    try:
        # 型や実装差異に備えて best-effort に設定
        if hasattr(client, "storage") and hasattr(client.storage, "client") and hasattr(client.storage.client, "headers"):
            client.storage.client.headers.update({"Authorization": f"Bearer {access_token}"})
    except Exception:
        pass

    # Realtime (任意)
    try:
        if hasattr(client, "realtime") and hasattr(client.realtime, "set_auth"):
            client.realtime.set_auth(access_token)  # type: ignore[attr-defined]
    except Exception:
        pass

    return client