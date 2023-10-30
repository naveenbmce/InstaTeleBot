from fastapi import FastAPI, Request
import os
import requests
import uvicorn

app = FastAPI()
BOT_KEY = os.getenv("TELEGRAM_BOT_KEY")
BOT_URL = f"https://api.telegram.org/bot{BOT_KEY}"

async def get_webhook_info():
    message_url = f"{BOT_URL}/getWebhookInfo"
    return await requests.get(message_url).json()
    
@app.get("/get_webhook/")
async def get_webhook():
    return await get_webhook_info()

if __name__ == '__main__':
    uvicorn.run(app)
