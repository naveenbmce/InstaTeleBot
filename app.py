from fastapi import FastAPI, Request
import os
import aiohttp

app = FastAPI()
BOT_KEY = os.environ["TELEGRAM_BOT_KEY"] # get the bot token from environment variable
BOT_URL = f"https://api.telegram.org/bot{BOT_KEY}"

async def get_webhook_info():
    """Get the current webhook information from Telegram API"""
    message_url = f"{BOT_URL}/getWebhookInfo"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(message_url) as response:
                webhook_info = await response.json()
                return webhook_info
        except Exception as e:
            print(e)
            return None

@app.get("/set_webhook")
async def url_setter():
    """Set the webhook URL for Telegram API"""
    PROG_URL = os.environ["DETA_SPACE_APP_HOSTNAME"] # get the server URL from environment variable
    set_url = f"{BOT_URL}/setWebHook?url=https://{PROG_URL}/open"
    print(set_url)
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(set_url) as response:
                webhook_result = await response.json()
                return webhook_result
        except Exception as e:
            print(e)
            return None

@app.get("/get_webhook/")
async def get_webhook():
    """Return the current webhook information"""
    return await get_webhook_info()

@app.post("/open")
async def http_handler(request: Request):
    """Handle the incoming messages from Telegram"""
    try:
        incoming_data = await request.json() # parse the request data as JSON
        prompt = incoming_data.get("message", {}).get("text", "No text found") # get the text from the message
        chat_id = incoming_data["message"]["chat"]["id"] # get the chat id from the message
    except Exception as e:
        print(e)
        return None

    if "message" not in incoming_data:
        print(incoming_data)
        return send_error(None, "Unknown error, lol, handling coming soon")

    if prompt in ["/start", "/help"]:
        response_text = (
            "welcome to InstgramBot"
        )
        payload = {"text": response_text, "chat_id": chat_id}
        message_url = f"{BOT_URL}/sendMessage"
        async with aiohttp.ClientSession() as session: # use aiohttp instead of requests
            try:
                async with session.post(message_url, json=payload) as response: # use post method to send message
                    resp = await response.json() # get the response data as JSON
                    return resp
            except Exception as e:
                print(e)
                return None
    
    return     

if __name__ == '__main__':
    uvicorn.run(app)
