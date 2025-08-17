import os
from supabase import create_client, Client  
import dotenv

dotenv.load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set in environment variables.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

if __name__ == "__main__":
    try:
        # 例: 'users' テーブルから1件取得してみる
        response = supabase.table("users").select("*").limit(1).execute()
        print("接続成功:", response.data)
    except Exception as e:
        print("接続失敗:", e)