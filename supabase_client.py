import os                           # ← これを追加
from supabase import create_client, Client
from dotenv import load_dotenv

# .envを読み込む
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set in .env file.")

# 匿名クライアント
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ユーザーのJWTでRLSを効かせるクライアント
def supabase_as(token: str) -> Client:
    c = create_client(SUPABASE_URL, SUPABASE_KEY)
    c.postgrest.auth(token)
    return c

