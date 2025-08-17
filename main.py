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