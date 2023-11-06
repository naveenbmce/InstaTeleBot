from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import StreamingResponse
import os
import aiohttp 
from aiohttp import ClientSession
from deta import Deta
import re
import json_repair
import uvicorn
import json
#Uncomment the below line if it is codespace
#from dotenv import load_dotenv
#load_dotenv()

app = FastAPI()
BOT_KEY = os.environ["TELEGRAM_BOT_KEY"] # get the bot token from environment variable
BOT_URL = f"https://api.telegram.org/bot{BOT_KEY}"
Deta_Key = os.environ["Deta_DB_KEY"]
deta = Deta(Deta_Key)
CHUNK_SIZE = 10 * 1024 * 1024  # 10 MB
Deta_Project_Id = os.environ["Deta_Project_Id"]


# Pattern for Instagram profile URL
profile_pattern = r"https?://(www\.)?instagram\.com/([a-zA-Z0-9_.]+)/?\??"
# Pattern for Instagram video URL
video_pattern = r"https?://(www\.)?instagram\.com/(tv|reel)/([a-zA-Z0-9_-]+)/?\??"
# Pattern for Instagram photo URL
photo_pattern = r"https?://(www\.)?instagram\.com/p/([a-zA-Z0-9_-]+)/?\??"

async def get_video_by_shortcode(_shortcode,_fileType,_username ):
  base_url = f'https://drive.deta.sh/v1/{Deta_Project_Id}/{_username}'
  headers = {'X-API-Key': Deta_Key}
  async with aiohttp.ClientSession(headers=headers) as session:
      async with session.get(f'{base_url}/files/download?name={_shortcode}.{_fileType}') as resp:
          if resp.status in (200, 206):
              data = await resp.read()
              return data
          else:
              return None
     
async def upload_large_file(_file_path,_file_type,_project_id,_folder_name,_file_name):
  base_url = f'https://drive.deta.sh/v1/{_project_id}/{_folder_name}'
  headers = {'X-API-Key': Deta_Key}
  async with aiohttp.ClientSession(headers=headers) as session:
    async with session.post(base_url + f'/uploads?name={_file_name}.{_file_type}') as response:
      response.raise_for_status()
      upload_id = (await response.json())['upload_id']
    part_number = 1
    async with aiohttp.ClientSession(headers=headers) as session:
      with open(_file_path, 'rb') as f:
        while True:
          chunk = f.read(CHUNK_SIZE)
          if not chunk:
            break
          async with session.post(
              base_url +
              f'/uploads/{upload_id}/parts?name={_file_name}.{_file_type}&part={part_number}',
              data=chunk) as response:
            response.raise_for_status()
          part_number += 1
    async with aiohttp.ClientSession(headers=headers) as session:
      async with session.patch(
          base_url + f'/uploads/{upload_id}?name={_file_name}.{_file_type}') as response:
        response.raise_for_status()
  return True

async def download_file(url, destination):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            with open(destination, 'wb') as fd:
                while True:
                    chunk = await resp.content.read(1024)  # 1k chunks
                    if not chunk:
                        break
                    fd.write(chunk)
    return destination

async def upload_file_by_username(url,file_type, _dest_file_name, _dest_folder_name):
    # Download the video file
    file_path = await download_file(url, f"{_dest_file_name}.{file_type}")
    # Call the upload_large_file function
    result = await upload_large_file(file_path,file_type, Deta_Project_Id, _dest_folder_name, _dest_file_name)
     # Delete the downloaded file
    os.remove(file_path)
    return result

async def get_all_Post_from_DB(username,_chat_id):
  try:
    db = deta.Base(username)
    response = db.fetch({"owner": username})# check if the response has any items
    itemcount = 0
    if response.items:
      # return True if the username exists
      for item in response.items:
        try:
          if item["is_video"] is True :
              itemcount = itemcount + 1
              video_file = await get_video_by_shortcode(item["shortcode"],"mp4",username)
              await send_message_video(video_file,item["caption"], _chat_id,item["shortcode"],item["height"],item["width"])
        except Exception as e:
          await send_error("Error in get_all_Post_from_DB #Loop items - " + str(e) ,_chat_id)
      return "Success"
    else:
      # return False if the username does not exist
      return "No video items"
  except Exception as e:
    await send_error("Error in get_all_Post_from_DB - " + str(e) ,_chat_id)
    return None

async def get_instagram_posts(username, count, RapidAPI_Key):
  try:
    headers = {
        'X-RapidAPI-Key': RapidAPI_Key,
        'X-RapidAPI-Host': "instagram-data1.p.rapidapi.com"
    }
    data = []  # initialize an empty list to store the posts
    end_cursor = None  # initialize a variable to store the end cursor
    has_more = True  # initialize a variable to store the has more flag
    requestURL = ""
    async with aiohttp.ClientSession() as session:  # create an aiohttp client session object
      while has_more:  # loop until there are no more posts
        if end_cursor:  # if there is an end cursor, add it as a parameter
          requestURL = "/user/feed?username=" + username + "&limit=" + str(
              count) + "&end_cursor=" + str(end_cursor)
        else:  # otherwise, just use the username and limit parameters
          requestURL = "/user/feed?username=" + username + "&limit=" + str(count)
        print(requestURL)
        async with session.get("https://instagram-data1.p.rapidapi.com" + requestURL, headers=headers) as response:  # make the request with the parameters
          status = response.status
          # print the status code for debugging
          print(status)
          if status == 429:
            raise Exception(f"Could not get a successful response given key")
          res_data = await response.text()  # read the response data
          await json_to_base_db(username, res_data)
          await get_all_media_to_drive(username)
          res_data = json_repair.loads(res_data)
          end_cursor = res_data["end_cursor"]  # update the end cursor value
          has_more = res_data["has_more"]  # update the has more flag
  except Exception as e:
    raise Exception(f"Could not get a successful response given key")

  return data  # return the data list

async def get_instagram_posts_rotateKey(username, count):
  rapid_db = deta.Base("Rapid_API_Keys")
  response = rapid_db.fetch({"api_name": "Instagram-Data"})
  items = response.items  # get the list of items from the response
  index = 0  # initialize a variable to store the key index
  success = False  # initialize a variable to store the success flag
  while not success and index < len(items):  # loop until success or no more keys left
    item = items[index]  # get the current item from the list
    if item["is_Primary"] is True:  # if the item is primary, use its key
      try:
        print("Function get_instagram_posts")
        await get_instagram_posts(username, count, item["key"])  # call the get_instagram_posts function with the key and store the data
        success = True  # set the success flag to True
        break  # break out of the loop
      except Exception as e:  # if there is an exception, handle it
        print(e)
        rapid_db.put(data={
            "key": item["key"],
            "api_name": "Instagram-Data",
            "is_Primary": False
        })  # update the primary flag to False in the database
        index += 1  # increment the index by 1
        if index < len(
            items
        ):  # if there is a next item in the list, update its primary flag to True in the database
          next_item = items[index]
          rapid_db.put(
              data={
                  "key": next_item["key"],
                  "api_name": "Instagram-Data",
                  "is_Primary": True
              })
          response = rapid_db.fetch({"api_name": "Instagram-Data"})
          items = response.items
    elif item["is_Primary"] is False:
      index += 1
  return "Success"

async def json_to_base_db(username, json_string):
  # Load the JSON data as a Python object
  json_data = json_repair.loads(json_string)
  itercount = 0
  # Loop through the JSON data
  for item in json_data["collector"]:
    try:
      # Extract the relevant fields from the item
      itercount = itercount + 1
      print(itercount)
      id = item.get("id", "")
      owner_id = item.get("owner", {}).get("id", "")
      owner = item.get("owner", {}).get("username", "")
      type = item.get("type", "")
      is_video = item.get("is_video", "")
      video_url = item.get("video_url", "") if is_video else ""
      height = item.get("dimension", {}).get("height", "")
      width = item.get("dimension", {}).get("width", "")
      thumbnail_src = item.get("thumbnail_src", "")
      taken_at_timestamp = item.get("taken_at_timestamp", "")
      shortcode = item.get("shortcode", "")
      caption = item.get("description", "")
      comments = item.get("comments", "")
      likes = item.get("likes", "")
      views = item.get("views", "") if is_video else ""
      location = item.get("location", {}).get("name", "") if isinstance(
          item.get("location"), dict) else ""
      hashtags = ",".join(
          item.get("hashtags",[])) if "hashtags" in item and item.get("hashtags") else ""
      mentions = ",".join(
          item.get("mentions",[])) if "mentions" in item and item.get("mentions") else ""
      # Create a dictionary with the key and other fields
      data = {
          "key": id,
          "owner_id": owner_id,
          "owner": owner,
          "type": type,
          "is_video": is_video,
          "video_url": video_url,
          "height": height,
          "width": width,
          "thumbnail_src": thumbnail_src,
          "taken_at_timestamp": taken_at_timestamp,
          "shortcode": shortcode,
          "caption": caption,
          "comments": comments,
          "likes": likes,
          "views": views,
          "location": location,
          "hashtags": hashtags,
          "mentions": mentions
      }
    except Exception as e:
      print(e)
      continue
    # Use the put() method to store the data in the Base
    db = deta.Base(username)
    db.put(data)

  master_data = {
      "key": json_data["id"],
      "username": username,
      "media_count": json_data["count"],
      "Tracking": True
  }
  master_db = deta.Base("Instagram_Master")
  master_db.put(master_data)
  return

async def get_all_media_to_drive(username):
  try:
    db = deta.Base(username)
    response = db.fetch({"owner": username})# check if the response has any items
    itemcount = 0
    if response.items:
      # return True if the username exists
      for item in response.items:
        try:
          if item["is_video"] is True :
              itemcount = itemcount + 1
              await upload_file_by_username(item["video_url"], "mp4", item["shortcode"], username)
        except Exception as e:
          # send_error("Error in get_all_Post_from_DB #Loop items - " + str(e) ,_chat_id)
          print(e)
      return "Success"
    else:
      # return False if the username does not exist
      return "No video items"
  except Exception as e:
    #await send_error("Error in get_all_Post_from_DB - " + str(e))
    print(e)
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

async def send_message_video(video_file, _caption, _chat_id, _fileName,_height,_width):
    async with aiohttp.ClientSession() as session:
        try:
            message_url = f"{BOT_URL}/sendVideo"
            data = aiohttp.FormData()
            data.add_field('chat_id', str(_chat_id))
            data.add_field('caption', _caption)
            data.add_field('supports_streaming', 'true')
            data.add_field('video', video_file, filename= _fileName+'.mp4')
            data.add_field('height', str(_height))
            data.add_field('width', str(_width))
            # Create an inline keyboard with a single button
            keyboard = {
                "inline_keyboard": [[
                    {
                        "text": "Open Post",
                        "url": "https://www.instagram.com/reel/"+_fileName
                    }
                ]]
            }# Add the keyboard to the form data
            data.add_field('reply_markup', json.dumps(keyboard))
            async with session.post(message_url, data=data) as response:
                resp = await response.json()
                return resp
        except Exception as e:
            print(e)
            await send_error("Error in send_message_video - " + str(e), _chat_id)
            return None

async def send_message_text(text_message,_chat_id):
    async with aiohttp.ClientSession() as session: # use aiohttp instead of requests
            try:
                message_url = f"{BOT_URL}/sendMessage"
                payload = {"text": text_message, "chat_id": _chat_id}
                async with session.post(message_url, json=payload) as response: # use post method to send message
                    resp = await response.json() # get the response data as JSON
                    return resp
            except Exception as e:
                print(e)
                return None

async def send_error(error_message,_chat_id):
    async with aiohttp.ClientSession() as session: # use aiohttp instead of requests
            try:
                message_url = f"{BOT_URL}/sendMessage"
                payload = {"text": error_message, "chat_id": _chat_id}
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

@app.get("/remove_webhook")
async def url_remover():
    remove_url = f"{BOT_URL}/deleteWebhook"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(remove_url) as response:
                webhook_result = await response.json()
                return webhook_result
        except Exception as e:
            print(e)
            return None

@app.get("/get_webhook/")
async def get_webhook():
    """Return the current webhook information"""
    return await get_webhook_info()

@app.get("/SaveKey")
def SaveKey():
  rapid_db = deta.Base("Rapid_API_Keys")
  rapid_db.put(data = {
    "key": "210233aecbmsh61a7cefbf2c880cp18192cjsnfa3cbdb526ff",
    "api_name": "Instagram-Data",
    "is_Primary" : True})
  rapid_db.put(data = {
    "key": "90fe634f95mshab51bdbbb21aab9p16e278jsndb3368361c77",
    "api_name": "Instagram-Data",
    "is_Primary" : False})
  rapid_db.put(
      data={
          "key": "9695caae8cmsh5842b4bfafdfb1bp1f2bb8jsncb130fa8e8be",
          "api_name": "Instagram-Data",
          "is_Primary": False
      })
  return "Success"

@app.post("/open")
async def http_handler(request: Request, background_tasks: BackgroundTasks):
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
          if(user_available):
            try:
              background_tasks.add_task(get_all_Post_from_DB, username=profile_username, _chat_id=chat_id)
              await send_message_text("Task Started !!! ",chat_id)
            except Exception as e:
              await send_error(response_text,chat_id)
          else:
            background_tasks.add_task(get_instagram_posts_rotateKey, username=profile_username, count=50)
            await send_message_text(" - User Not Exist in db - Download Task Started ",chat_id)
            
    else:
        response_text = ("This is not a valid Instagram URL")
        await send_message_text(response_text,chat_id)
    
    return     

@app.get("/uploadfile")
async def uploadfile(request: Request):
    url = request.query_params.get("url")
    file_type = "mp4"
    filename = "TestFile"
    username = "Instagram"

    if url and file_type and filename and username:
        await upload_file_by_username(url, file_type, filename, username)
        return "success"
    else:
        return "Missing parameters in query string"

async def get_video_Exist_DB(shortcode):
  try:
    db = deta.Base("Instagram_Master")
    response = db.fetch()# check if the response has any items
    if response.items:
      # return True if the username exists
      for item in response.items:
        video_file = await get_video_by_shortcode(shortcode,"mp4",item["username"])
        if video_file is not None:
           return video_file
    else:
      # return False if the username does not exist
      return False
  except Exception as e:
    return None

async def stream_video(data: bytes):
    # This is an async generator function that yields chunks of the video file
    chunk_size = 1024 * 1024  # Chunk size of 1MB
    for i in range(0, len(data), chunk_size):
        yield data[i : i + chunk_size]

@app.get("/getvideo")
async def getvideo(request: Request):
    url = request.query_params.get("url")
    if url:
        shortcode = is_Instagram_video(url)
        if(shortcode):
          video_file = await get_video_Exist_DB(shortcode)
          if(video_file is not None):
            return StreamingResponse(stream_video(video_file), media_type="video/mp4")
          else:
             return "No video found in db!!"
        else :
           return "Url is not Valid !! "
    else:
        return "Missing parameters in query string"

if __name__ == '__main__':
    uvicorn.run(app)
