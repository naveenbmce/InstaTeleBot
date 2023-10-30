from fastapi import FastAPI, Request
import os
import aiohttp

app = FastAPI()
BOT_KEY = os.getenv("TELEGRAM_BOT_KEY")
BOT_URL = f"https://api.telegram.org/bot{BOT_KEY}"

async def get_webhook_info():
    message_url = f"{BOT_URL}/getWebhookInfo"
    async with aiohttp.ClientSession() as session:
        async with session.get(message_url) as response:
            data = await response.json()
            return data
    
@app.get("/get_webhook/")
async def get_webhook():
    return await get_webhook_info()


if __name__ == '__main__':
    uvicorn.run(app)
