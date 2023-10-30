from fastapi import FastAPI, Request
import os
import aiohttp
from deta import Deta
import re

app = FastAPI()
BOT_KEY = os.environ["TELEGRAM_BOT_KEY"] # get the bot token from environment variable
BOT_URL = f"https://api.telegram.org/bot{BOT_KEY}"
Deta_Key = os.environ["Deta_DB_KEY"]
deta = Deta(Deta_Key)


# Pattern for Instagram profile URL
profile_pattern = r"https?://(www\.)?instagram\.com/([a-zA-Z0-9_.]+)/?\??"
# Pattern for Instagram video URL
video_pattern = r"https?://(www\.)?instagram\.com/(tv|reel)/([a-zA-Z0-9_-]+)/?\??"
# Pattern for Instagram photo URL
photo_pattern = r"https?://(www\.)?instagram\.com/p/([a-zA-Z0-9_-]+)/?\??"

async def get_all_Post_from_DB(username,_chat_id):
  try:
    db = deta.Base(username)
    response = db.fetch({"owner": username})# check if the response has any items
    itemcount = 0
    if response.items:
      # return True if the username exists
      for item in responsedetails.items:
        try:
          if item["is_video"] is True :
              itemcount = itemcount + 1
              payload = {"text": str(itemcount), "chat_id": chat_id}
              message_url = f"{BOT_URL}/sendMessage"
              await send_message_text(item["video_url"], chat_id)
        except Exception as e:
          await send_error("Error in get_all_Post_from_DB #Loop items - " + str(e) ,_chat_id)
      return True
    else:
      # return False if the username does not exist
      return False
  except Exception as e:
    await send_error("Error in get_all_Post_from_DB - " + str(e) ,_chat_id)
    return None

async def is_Username_exist(username,_chat_id):
  try:
    db = deta.Base("Instagram_Master")
    response = db.fetch({"username": username})# check if the response has any items
    if response.items:
      # return True if the username exists
      return True
    else:
      # return False if the username does not exist
      return False
  except Exception as e:
    await send_error("Error in is_Username_exist - " + str(e) ,_chat_id)
    return None
    
def is_Instagram_video(url):
  # Check if the url is a video URL
  video_match = re.match(video_pattern, url)
  if video_match:
    # Return the shortcode from the second group of the match object
    shortcode = video_match.group(3)
    return shortcode
  else:
    # Return False
    return False

def is_Instagram_profile(url):
  # Check if the url is a profile URL
  profile_match = re.match(profile_pattern, url)
  if profile_match:
    # Return the username from the second group of the match object
    username = profile_match.group(2)
    return username
  else:
    # Return False
    return False

def is_Instagram_photo(url):
  # Check if the url is a photo URL
  photo_match = re.match(photo_pattern, url)
  if photo_match:
    # Return the shortcode from the first group of the match object
    shortcode = photo_match.group(2)
    return shortcode
  else:
    # Return False
    return False

async def send_message_text(text_message,chat_id):
    async with aiohttp.ClientSession() as session: # use aiohttp instead of requests
            try:
                message_url = f"{BOT_URL}/sendMessage"
                payload = {"text": text_message, "chat_id": chat_id}
                async with session.post(message_url, json=payload) as response: # use post method to send message
                    resp = await response.json() # get the response data as JSON
                    return resp
            except Exception as e:
                print(e)
                return None

async def send_error(chat_id, error_message):
    async with aiohttp.ClientSession() as session: # use aiohttp instead of requests
            try:
                message_url = f"{BOT_URL}/sendMessage"
                payload = {"text": error_message, "chat_id": chat_id}
                async with session.post(message_url, json=payload) as response: # use post method to send message
                    resp = await response.json() # get the response data as JSON
                    return resp
            except Exception as e:
                print(e)
                return None


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
        return await send_error(None, "Unknown error, lol, handling coming soon")

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
    if "instagram.com" in prompt:
      if is_Instagram_video(prompt):
          video_shortcode = is_Instagram_video(prompt)
          response_text = "This is a video URL - " + video_shortcode
          await send_message_text(response_text,chat_id)
      elif is_Instagram_photo(prompt):
          photo_shortcode = is_Instagram_photo(prompt)
          response_text = "This is a photo URL - " + photo_shortcode
          await send_message_text(response_text,chat_id)
      elif is_Instagram_profile(prompt):
          profile_username = is_Instagram_profile(prompt)
          response_text = "This is a profile URL - " + profile_username + " - Requested chat ID - " + str(chat_id)
          user_available = await is_Username_exist(profile_username,chat_id)
          response_text = response_text + " - is available - " + str(user_available)
          await send_message_text(response_text,chat_id)
    else:
        response_text = ("This is not a valid Instagram URL")
        await send_message_text(response_text,chat_id)
    
    return     

if __name__ == '__main__':
    uvicorn.run(app)
