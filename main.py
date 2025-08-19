from fastapi import FastAPI

# FastAPIのアプリケーションインスタンスを作成し、「app」という名前を付けます
app = FastAPI()

# ルートURL ("/") にアクセスしたときの処理を定義
@app.get("/")
def read_root():
    return {"message": "Hello, World!"}

#仮想環境に入ってね：Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process
# .\venv\Scripts\activate
# uvicorn main:app --reload
# uvicorn main:app --host   
#pip install fastapi uvicorn python-dotenv requests
# main.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from supabase_client import supabase  # 作成したSupabaseクライアント

app = FastAPI()

# リクエストボディの型を定義
class UserSignUpRequest(BaseModel):
    email: str
    password: str

# ユーザー登録用のエンドポイント
@app.post("/auth/signup")
def signup(user_request: UserSignUpRequest):
    try:
        # Supabase Authの sign_up_with_password メソッドを呼び出す
        response = supabase.auth.sign_up(
            {
                "email": user_request.email,
                "password": user_request.password,
            }
        )
        
        # 登録成功時の処理
        # Supabaseは登録成功時にセッション情報を含むレスポンスを返します
        if response.user:
            return {"message": "User signed up successfully. Check your email for confirmation."}
        else:
            # 登録は成功したがユーザーオブジェクトが返ってこなかった場合（稀）
            raise HTTPException(status_code=500, detail="Internal server error.")

    except Exception as e:
        # Supabaseからのエラーをキャッチ
        # 例えば、メールアドレスがすでに使われている場合など
        raise HTTPException(status_code=400, detail=str(e))
    # main.py
# (上記コードの続き)
# リクエストボディの型を定義
class UserSignInRequest(BaseModel):
    email: str
    password: str

# ユーザーログイン用のエンドポイント
@app.post("/auth/signin")
def signin(user_request: UserSignInRequest):
    try:
        # Supabase Authの sign_in_with_password メソッドを呼び出す
        response = supabase.auth.sign_in_with_password(
            {
                "email": user_request.email,
                "password": user_request.password,
            }
        )
        
        # ログイン成功時の処理
        # response.session には access_token や refresh_token が含まれる
        if response.session:
            return {
                "message": "User signed in successfully.",
                "access_token": response.session.access_token,
                "user": response.user.dict()
            }
        else:
            # ログインは成功したがセッション情報が返ってこなかった場合（稀）
            raise HTTPException(status_code=500, detail="Internal server error.")
    
    except Exception as e:
        # Supabaseからのエラーをキャッチ
        # 例えば、パスワードが間違っている場合など
        raise HTTPException(status_code=400, detail=str(e))