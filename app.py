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

@app.get("/set_webhook")
async def url_setter():
    PROG_URL = os.getenv("DETA_SPACE_APP_HOSTNAME")
    set_url = f"{BOT_URL}/setWebHook?url=https://{PROG_URL}/open"
    async with aiohttp.ClientSession() as session:
        async with session.get(set_url) as response:
            resp = await response.json()
            return resp

@app.get("/get_webhook/")
async def get_webhook():
    return await get_webhook_info()

@app.post("/open")
async def http_handler(request: Request):
    incoming_data = await request.json()
    #prompt = incoming_data["message"]["text"]
    prompt = incoming_data.get("message", {}).get("text", "No text found")
    chat_id = incoming_data["message"]["chat"]["id"]
    if "message" not in incoming_data:
        print(incoming_data)
        return send_error(None, "Unknown error, lol, handling coming soon")

    if prompt in ["/start", "/help"]:
        response_text = (
            "welcome to InstgramBot"
        )
        payload = {"text": response_text, "chat_id": chat_id}
        message_url = f"{BOT_URL}/sendMessage"
        requests.post(message_url, json=payload).json()
        return
    
    
    return     


if __name__ == '__main__':
    uvicorn.run(app)
