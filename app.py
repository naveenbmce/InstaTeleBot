import io
from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import StreamingResponse
import os
import aiohttp
from aiohttp import ClientSession, web
from deta import Deta
import re
import json_repair
import uvicorn
import json
import urllib.request
#import telegram
from pyrogram import Client
import asyncio
from pyrogram.types import InlineKeyboardMarkup,InlineKeyboardButton,InputMediaPhoto,InputMediaVideo
import time
import http.client
import subprocess
#Uncomment the below line if it is codespace
from dotenv import load_dotenv
load_dotenv()

app = FastAPI()
BOT_KEY = os.environ["TELEGRAM_BOT_KEY"] # get the bot token from environment variable
BOT_URL = f"https://api.telegram.org/bot{BOT_KEY}"
Deta_Key = os.environ["Deta_DB_KEY"]
deta = Deta(Deta_Key)
CHUNK_SIZE = 10 * 1024 * 1024  # 10 MB
Deta_Project_Id = os.environ["Deta_Project_Id"]
#bot = telegram.Bot(token=BOT_KEY)
api_id = os.environ["TELEGRAM_BOT_API_ID"] #1727796
api_hash = os.environ["TELEGRAM_BOT_API_HASH"]#"e291e0f8cc72e1d037b90ba177a70449"


# Pattern for Instagram profile URL
profile_pattern = r"https?://(www\.)?instagram\.com/([a-zA-Z0-9_.]+)/?\??"
# Pattern for Instagram video URL
video_pattern = r"https?://(www\.)?instagram\.com/(tv|reel)/([a-zA-Z0-9_-]+)/?\??"
# Pattern for Instagram photo URL
photo_pattern = r"https?://(www\.)?instagram\.com/p/([a-zA-Z0-9_-]+)/?\??"

def format_size(bytes):
    # Define the step to convert bytes to higher units
    step = 1024

    # Convert bytes to KB
    kb = bytes / step

    # Check if the value is less than one KB
    if kb < 1:
        # Return the value in bytes with one decimal place
        return f"{bytes:.1f} bytes"
    else:
        # Convert KB to MB
        mb = kb / step

        # Check if the value is less than one MB
        if mb < 1:
            # Return the value in KB with one decimal place
            return f"{kb:.1f} KB"
        else:
            # Return the value in MB with one decimal place
            return f"{mb:.1f} MB"

def video_to_thumbnail(video_file, thumbnail_file, time):
    
    # Use ffmpeg command to extract a frame at the given time
    command = ["ffmpeg", "-i", video_file, "-ss", time, "-vframes", str(1), thumbnail_file]
    # Run the command and capture the output
    output = subprocess.run(command, capture_output=True)
    # Check if the command was successful
    if output.returncode == 0:
        # Return the thumbnail file name
        return thumbnail_file
    else:
        # Return an error message
        return output.stderr.decode()

async def get_post_details_by_shortcode(_shortcode,_username):
    try:
        db = deta.Base(_username)
        response = db.fetch({"shortcode": _shortcode})# check if the response has any items
        if response.items:
          return response
        else:
          return None
    except Exception as e:
      print(str(e))
      return None 

async def get_post_by_shortcode(_shortcode,_fileType,_username):
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

async def download_video(url_link, video_name):
    try:
      downloadreponse = urllib.request.urlretrieve(url_link, video_name)
      return video_name
    except Exception as e:
      print(str(e))
      return None

async def upload_file_by_username(url,file_type, _dest_file_name, _dest_folder_name):
    # Download the video file
    #file_path = await download_file(url, f"{_dest_file_name}.{file_type}")
    #file_size = os.path.getsize (file_path)
    #os.remove(file_path)
    file_path = await download_video(url, f"{_dest_file_name}.{file_type}")
    # Call the upload_large_file function
    if file_path is not None:
      result = await upload_large_file(file_path,file_type, Deta_Project_Id, _dest_folder_name, _dest_file_name)

    # Delete the downloaded file
    #os.remove(file_path)
    return file_path

# Define a custom progress function
async def progress(current, total, message, start):
    # Calculate the percentage and the elapsed time
    percentage = current * 100 / total
    elapsed_time = round(time.time() - start)

    # Format the progress message
    progress_message = f"📤 Uploading video...\n\n▪️ Progress: {percentage:.1f}%\n▪️ Speed: {format_size(current / elapsed_time)}/s\n▪️ ETA: {round((total - current) / (current / elapsed_time))} seconds"

    # Edit the message with the progress message
    await message.edit(progress_message)

async def send_telegram_media(file_name,_caption, _chat_id, _fileName,_height,_width):
  try:
    root, extension = os.path.splitext(file_name)
    _new_caption =_caption[:1024]
    keyboard = InlineKeyboardMarkup([
        [ # Row 1 button
            InlineKeyboardButton(
                text="Open Post",
                url="https://www.instagram.com/reel/"+_fileName
            ),
            InlineKeyboardButton(
                text="Download Post",
                url="https://testwebservice-8vm8.onrender.com/getvideo?url=https://www.instagram.com/reel/"+_fileName
            )
        ]
    ])
    #await bot.send_video(chat_id = _chat_id, video=video_file,caption = _caption, height = _height,width =_width,supports_streaming=True)
    async with Client("my_account", api_id, api_hash,bot_token=BOT_KEY) as pyroapp:
        # Send a message to indicate the start of the upload
        message = await pyroapp.send_message(chat_id=_chat_id, text="📤 Uploading media...")
        # Get the current time
        start = time.time()
        
        try:
            if extension == ".mp4":
              if os.path.exists(f'thumb_{root}.jpg'):
                 thumb = f'thumb_{root}.jpg'
              else:
                 thumb = None
            # Send the video with the custom progress function
              #await pyroapp.send_video(chat_id  = _chat_id, video = file_name,caption = _caption,height = _height,width =_width,supports_streaming=True,reply_markup=keyboard, progress=progress, progress_args=(message, start))
              await pyroapp.send_video(chat_id  = _chat_id, video = file_name,caption = _new_caption,height = _height,width =_width,supports_streaming=True,reply_markup=keyboard,thumb=thumb)
            elif extension == ".jpg":
              #await pyroapp.send_photo(chat_id  = _chat_id, photo = file_name,caption = _caption,reply_markup=keyboard, progress=progress, progress_args=(message, start))
              await pyroapp.send_photo(chat_id  = _chat_id, photo = file_name,caption = _new_caption,reply_markup=keyboard)
        except:
          time.sleep(5)
          if extension == ".mp4":
            await pyroapp.send_video(chat_id  = _chat_id, video = file_name,caption = _new_caption,height = _height,width =_width,supports_streaming=True,reply_markup=keyboard,thumb=thumb)
          elif extension == ".jpg":
            await pyroapp.send_photo(chat_id  = _chat_id, photo = file_name,caption = _new_caption,reply_markup=keyboard)
        finally:
            #os.remove(file_name)
            await message.delete()
    return "success"
  except Exception as e:
    await send_error(str(e),_chat_id)
    return None

async def send_telegram_photo(photo_file_path,_caption, _chat_id, _fileName):
  try:
    keyboard = InlineKeyboardMarkup([
        [ # Row 1 button
            InlineKeyboardButton(
                text="Open Post",
                url="https://www.instagram.com/reel/"+_fileName
            ),
            InlineKeyboardButton(
                text="Download Post",
                url="https://testwebservice-8vm8.onrender.com/getvideo?url=https://www.instagram.com/reel/"+_fileName
            )
        ]
    ])
    _new_caption=_caption[:1024]
    #await bot.send_video(chat_id = _chat_id, video=video_file,caption = _caption, height = _height,width =_width,supports_streaming=True)
    async with Client("my_account", api_id, api_hash,bot_token=BOT_KEY) as pyroapp:
        # Send a message to indicate the start of the upload
        message = await pyroapp.send_message(chat_id=_chat_id, text="📤 Uploading photo...")
        # Get the current time
        start = time.time()
        try:
          # Send the video with the custom progress function
            #await pyroapp.send_photo(chat_id  = _chat_id, photo = photo_file_path,caption = _caption,reply_markup=keyboard, progress=progress, progress_args=(message, start))
            await pyroapp.send_photo(chat_id  = _chat_id, photo = photo_file_path,caption = _new_caption,reply_markup=keyboard)
          # Delete the progress message
        except:
           await pyroapp.send_photo(chat_id  = _chat_id, photo = photo_file_path,caption = _new_caption,reply_markup=keyboard)
        finally:
            os.remove(photo_file_path)
            await message.delete()
    return "success"
  except Exception as e:
    await send_error(str(e),_chat_id)
    return None

async def send_telegram_group_media(media_urls, _caption, _chat_id, _fileName):
    try:
        keyboard = InlineKeyboardMarkup([
            [ # Row 1 button
                InlineKeyboardButton(
                    text="Open Post",
                    url="https://www.instagram.com/reel/"+_fileName
                ),
                InlineKeyboardButton(
                    text="Download Post",
                    url="https://testwebservice-8vm8.onrender.com/getvideo?url=https://www.instagram.com/reel/"+_fileName
                )
            ]
        ])
        #_caption:_caption[:1024]
        async with Client("my_account", api_id, api_hash, bot_token=BOT_KEY) as pyroapp:
            # Send a message to indicate the start of the upload
            message = await pyroapp.send_message(chat_id=_chat_id, text="📤 Uploading media...")
            # Get the current time
            start = time.time()
            try:
                # Create a list to hold the media
                media = []
                # Loop through each URL
                for url in media_urls:
                    # Check if the URL ends with ".mp4"
                    if url.endswith(".mp4"):
                        # Add it as a video
                        media.append(InputMediaVideo(url))
                    # Check if the URL ends with ".jpg"
                    elif url.endswith(".jpg"):
                        # Add it as a photo
                        media.append(InputMediaPhoto(url))
                # Send the media with the custom progress function
                await pyroapp.send_media_group(
                    chat_id=_chat_id,
                    media=media
                )
                await pyroapp.send_message(chat_id=_chat_id, text=_caption)
            except:
                await pyroapp.send_media_group(
                    chat_id=_chat_id,
                    media=media
                )
            finally:
                await message.delete()
        return "success"
    except Exception as e:
        await send_error(str(e), _chat_id)
        return None

async def get_all_Post_from_DB(username,_chat_id):
  try:
    db = deta.Base(username)
    response = db.fetch({"owner": username})# check if the response has any items
    itemcount = 0
    if response.items:
      # return True if the username exists
      for item in response.items:
        media_items = item.get('media_url')
        for media_item in media_items:
          media_shortcode = media_item.get('short_code')
          media_type = media_item.get('media_type')
          original_height = media_item.get('height')
          original_width = media_item.get('width') 
          caption = item["caption"]
        try:
          file_extension = 'mp4' if media_type == 'video' else 'jpg'
          itemcount = itemcount + 1
          video_data = await get_post_by_shortcode(media_shortcode,file_extension,username)
          media_filename = f'{media_shortcode}.{file_extension}'
          with open(media_filename, 'wb') as file: # open a file with the same name and type as the video
            file.write(video_data)

          await send_telegram_media(media_filename,caption[:1024], _chat_id,media_shortcode,original_height,original_width)
          os.remove(media_filename)
          time.sleep(3)
        except Exception as e:
          await send_error("Error in get_all_Post_from_DB #Loop items - " + str(e) ,_chat_id)
      return "Success"
    else:
      # return False if the username does not exist
      return "No video items"
  except Exception as e:
    await send_error("Error in get_all_Post_from_DB - " + str(e) ,_chat_id)
    return None

async def get_all_instagram_posts_v1(username, count, RapidAPI_Key,_chat_id):
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
          await json_to_base_db(username, res_data,_chat_id)
          #await get_all_media_to_drive(username)
          res_data = json_repair.loads(res_data)
          end_cursor = res_data["end_cursor"]  # update the end cursor value
          has_more = res_data["has_more"]  # update the has more flag
  except Exception as e:
    raise Exception(f"Could not get a successful response given key")

  return data  # return the data list

async def get_all_instagram_posts_v2(userid, count, RapidAPI_Key,_chat_id):
  try:
    headers = {
        'X-RapidAPI-Key': RapidAPI_Key,
        'X-RapidAPI-Host': "rocketapi-for-instagram.p.rapidapi.com"
    }
    #payload = "{\r\"id\": 12281817,\r\"count\": 12,\r\"max_id\": null\r}"
    data = []  # initialize an empty list to store the posts
    request_count = 0
    media_count = 0
    end_cursor = None  # initialize a variable to store the end cursor
    has_more = True  # initialize a variable to store the has more flag
    requestURL = "/instagram/user/get_media"
    conn = http.client.HTTPSConnection("rocketapi-for-instagram.p.rapidapi.com") # create an HTTPS connection object
    while has_more:  # loop until there are no more posts
        payload = {"id": int(userid), "count": count, "max_id": end_cursor} # create the payload as a dictionary
        print(requestURL)
        conn.request("POST", requestURL, json.dumps(payload), headers) # make the request with the parameters
        res = conn.getresponse() # get the response object
        status = res.status
        # print the status code for debugging
        print(status)
        if status == 200:
            request_count = request_count + 1
            res_data = res.read() # read the response data as bytes
            res_data = res_data.decode("utf-8") # decode the bytes to a string
            res_data = json_repair.loads(res_data)
            #await json_to_base_db(username, res_data,_chat_id)
            #await get_all_media_to_drive(username)
            
            end_cursor = res_data["response"]["body"].get("next_max_id")
            has_more = res_data["response"]["body"].get("more_available")  # update the has more flag
            #has_more = False
            data.extend(res_data["response"]["body"]["items"])
        else:
            has_more = False
            raise Exception(f"Could not get a successful response given key")
    print(str(request_count))
    return data,request_count
  except Exception as e:
    raise Exception(f"Could not get a successful response given key")

async def upload_and_send_all_post(datalist,chat_id):
  try:
   itercount = 0
   datalist.reverse()
   userid = ""
   Total_media = len(datalist)
   for sub_item in datalist:
    itercount = itercount + 1
    try:
      media_objects = []
      media_list = []
      # Extract the relevant fields from the item
      message_response  = await send_message_text_old(f'📤 Downloading post...{str(itercount)}/{Total_media}',chat_id)
      messageid = message_response["result"]["message_id"]
      print(itercount)
      id = sub_item.get("id", "")
      username = sub_item.get("user", {}).get("username", "")
      owner_id = sub_item.get("user", {}).get("pk", "")
      userid = str(owner_id)
      original_height = sub_item.get("original_height", "")
      original_width = sub_item.get("original_width", "")
      caption = sub_item.get("caption", {}).get("text", "")
      product_type = sub_item.get("product_type", "")
      if product_type == "clips":
        is_video = True
      else:
        is_video = False
      shortcode = sub_item.get("code", "")
      taken_at_timestamp = sub_item.get("taken_at", "")
      comments = sub_item.get("comment_count", "")
      likes = sub_item.get("like_count", "")
      views = sub_item.get("view_count", "")
      location = sub_item.get("location", {}).get("name", "")
      thumbnail_src = ""
      hashtags = ""
      mentions = ""
      video_versions = sub_item.get('video_versions', [])
      if(len(video_versions) >= 1):
        media_candidates = video_versions
        thumb_versions = sub_item.get('image_versions2', {})
        thumbnail_candidates = thumb_versions.get('candidates', [])
      else:
        image_versions = sub_item.get('image_versions2', {})
        media_candidates = image_versions.get('candidates', [])
      carousel_count = 0
      for carousel in sub_item.get('carousel_media', []):
          # Get the list of candidates
          carousel_count = 1 + carousel_count
          candidates = carousel.get('image_versions2', {}).get('candidates', [])
          # Get the last candidate (1080p image)
          last_candidate = candidates[0] if candidates else {}
          # Get the URL of the image
          image_url = last_candidate.get('url', '')
          height = last_candidate.get('height', '')
          width = last_candidate.get('width', '')
          # Create an object with media type and URL
          if image_url :
            media_object = {
                'media_type': 'image' if carousel.get('media_type') == 1 else 'video',
                'url': image_url,
                'short_code': f'{sub_item.get("code", "")}_{carousel_count}',
                'height': height,
                'width': width,
                'thumb': None if sub_item.get('media_type') == 1 else sub_item.get("thumbnail_src", "")
            }
            # Add the object to the list
            media_objects.append(media_object)

      if not media_objects:
        thumbnail_url = None
        if sub_item.get('media_type') == 1:
           thumbnail_url = None
        else:
           for thum_item in thumbnail_candidates:
              if thum_item.get('width') == 750:
                thumbnail_url = thum_item.get('url')

        last_candidate = media_candidates[0]
        image_url = last_candidate.get('url', '')
        print(image_url)
        media_object = {
                'media_type': 'image' if sub_item.get('media_type') == 1 else 'video',
                'url': image_url,
                'short_code': sub_item.get("code", ""),
                'height': sub_item.get("original_height", ""),
                'width': sub_item.get("original_width", ""),
                'thumb': thumbnail_url
            }
        media_objects.append(media_object)
      
      if(len(media_objects) > 1):
            item_type = "GraphSidecar"
      elif media_objects[0].get('media_type') == "image":
            item_type = "GraphImage"
      elif media_objects[0].get('media_type') == "video":
            item_type = "GraphVideo"
      deta_put_instagram(username=username,key_id=id,owner_id=owner_id,item_type=item_type,is_video=is_video,media_url=media_objects,
                  thumbnail_src=thumbnail_src,taken_at_timestamp=taken_at_timestamp,shortcode=shortcode,
                  caption=caption,comments=comments,likes=likes,views=views,location=location,hashtags=hashtags,mentions=mentions)
      await delete_message(chat_id,messageid)
      for item_media in media_objects:
        if is_video:
          media_file_name = await upload_file_by_username(item_media.get('url'), "mp4", item_media.get('short_code'), username)
          root, extension = os.path.splitext(media_file_name)
          thumb_media_file_name  = video_to_thumbnail(media_file_name, f'thumb_{root}.jpg', "00:00:01.000")
          #thumb_media_file_name = await upload_file_by_username(item_media.get('thumb'), "jpg", "thumb_"+str(shortcode), username)
        else:
          media_file_name = await upload_file_by_username(item_media.get('url'), "jpg", item_media.get('short_code'), username)
        media_list.append(media_file_name)
        
      if len(media_list) > 1:
        await send_telegram_group_media(media_list,caption, chat_id,shortcode)
      elif len(media_list) == 1 :
        file_name =  media_list[0]
        await send_telegram_media(file_name,caption, chat_id,shortcode,original_height,original_width)
      time.sleep(5)
      for filename in media_list:
        root, extension = os.path.splitext(filename)
        if extension == ".mp4":
          os.remove(filename)
          os.remove(f'thumb_{root}.jpg')
        else:
           os.remove(filename)
      
      
    except Exception as e:
        print(e)
        continue

   master_data = {
      "key": userid,
      "username": username,
      "media_count": "",
      "Tracking": False,
      "chat_id":chat_id
    }
   master_db = deta.Base("Instagram_Master")
   master_db.put(master_data)
   return True
  except Exception as e:
    print(e)
    return False

async def get_all_instagram_posts_rotateKey(userid, count,_chat_id):
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
        #await get_all_instagram_posts_v1(username, count, item["key"],_chat_id)  # call the get_instagram_posts function with the key and store the data
        response_data,request_count = await get_all_instagram_posts_v2(userid, count, item["key"],_chat_id)
        is_task_complete = await upload_and_send_all_post(response_data,_chat_id)

        if is_task_complete:
          summary_messgae = f"✔️ Task Completed...\n\n▪️ Total Fetched Media: {str(len(response_data))}\n▪️ Request Consumed: {str(request_count)}"
          await send_message_text_old(summary_messgae,_chat_id)
        #await get_all_Post_from_DB(username, _chat_id)
        
        success = True  # set the success flag to True
        break  # break out of the loop
      except Exception as e:  # if there is an exception, handle it
        print(e)
        rapid_db.update({"is_Primary": False}, key= item["key"])

       # update the primary flag to False in the database
        index += 1  # increment the index by 1
        if index < len(items):  # if there is a next item in the list, update its primary flag to True in the database
          next_item = items[index]
          rapid_db.update({"is_Primary": True}, key= next_item["key"])
          response = rapid_db.fetch({"api_name": "Instagram-Data"})
          items = response.items
        else:
          next_item = items[0]
          rapid_db.update({"is_Primary": True}, key= next_item["key"])
          response = rapid_db.fetch({"api_name": "Instagram-Data"})
          items = response.items
          break
    elif item["is_Primary"] is False:
      index += 1
  return "Success"

async def get_new_instagram_posts_rotateKey(username):
  rapid_db = deta.Base("Rapid_API_Keys")
  response = rapid_db.fetch({"api_name": "Instagram-Data"})
  items = response.items  # get the list of items from the response
  index = 0  # initialize a variable to store the key index
  success = False  # initialize a variable to store the success flag
  while not success and index < len(items):  # loop until success or no more keys left
    item = items[index]  # get the current item from the list
    if item["is_Primary"] is True:  # if the item is primary, use its key
      try:
        print("Function get_new_instagram_posts")
        newpost = await get_instagram_newpost_by_username(username)  # call the get_instagram_posts function with the key and store the data
        json_data = json_repair.loads(newpost)
        success = True  # set the success flag to True
        return json_data
        break  # break out of the loop
      except Exception as e:  # if there is an exception, handle it
        print(e)
        rapid_db.update({"is_Primary": False}, key= item["key"])
       # update the primary flag to False in the database
        index += 1  # increment the index by 1
        if index < len(items):  # if there is a next item in the list, update its primary flag to True in the database
          next_item = items[index]
          rapid_db.update({"is_Primary": True}, key= next_item["key"])
          response = rapid_db.fetch({"api_name": "Instagram-Data"})
          items = response.items
    elif item["is_Primary"] is False:
      index += 1
  return "Success"

async def get_update_post_handler():
  try:
    db = deta.Base("Instagram_Master")
    response = db.fetch()# check if the response has any items
    if response.items:
      # return True if the username exists
      for item in response.items:
        media_list =[]
        media_objects = []
        if item["username"] != "others" and item["Tracking"] == True:
           chat_ids = list(filter(None, str(item["chat_id"]).split(';')))
           newpostresponse = await get_new_instagram_posts_rotateKey(item["username"])
           if newpostresponse:
            newposts = newpostresponse[0].get('feed',{}).get('data',[])
            for sub_item in newposts:
              post_shortcode = sub_item.get('code')
              ispostExist = await get_post_details_by_shortcode(post_shortcode,item["username"])
              if ispostExist is None:
                id = sub_item.get("id", "")
                username = sub_item.get("user", {}).get("username", "")
                owner_id = sub_item.get("user", {}).get("pk", "")
                original_height = sub_item.get("original_height", "")
                original_width = sub_item.get("original_width", "")
                caption = sub_item.get("caption", {}).get("text", "")
                product_type = sub_item.get("product_type", "")
                if product_type == "clips":
                  is_video = True
                else:
                  is_video = False
                shortcode = sub_item.get("code", "")
                taken_at_timestamp = sub_item.get("taken_at", "")
                comments = sub_item.get("comment_count", "")
                likes = sub_item.get("like_count", "")
                views = sub_item.get("view_count", "")
                location = sub_item.get("location", {}).get("name", "")
                thumbnail_src = ""
                hashtags = ""
                mentions = ""
                video_versions = sub_item.get('video_versions', [])
                if(len(video_versions) >= 1):
                  media_candidates = video_versions
                else:
                  image_versions = sub_item.get('image_versions2', {})
                  media_candidates = image_versions.get('candidates', [])
                
                for carousel in sub_item.get('carousel_media', []):
                    # Get the list of candidates
                    candidates = carousel.get('image_versions2', {}).get('candidates', [])
                    # Get the last candidate (1080p image)
                    last_candidate = candidates[-1] if candidates else {}
                    # Get the URL of the image
                    image_url = last_candidate.get('url', '')
                    height = last_candidate.get('height', '')
                    width = last_candidate.get('width', '')
                    # Create an object with media type and URL
                    if image_url :
                      media_object = {
                          'media_type': 'image' if carousel.get('media_type') == 1 else 'video',
                          'url': image_url,
                          'short_code': carousel.get('shortcode'),
                          'height': height,
                          'width': width
                      }
                      # Add the object to the list
                      media_objects.append(media_object)

                if not media_objects:
                  last_candidate = media_candidates[-1]
                  image_url = last_candidate.get('url', '')
                  print(image_url)
                  media_object = {
                          'media_type': 'image' if sub_item.get('media_type') == 1 else 'video',
                          'url': image_url,
                          'short_code': sub_item.get("code", ""),
                          'height': sub_item.get("original_height", ""),
                          'width': sub_item.get("original_width", "")
                      }
                  media_objects.append(media_object)
                
                if(len(media_objects) > 1):
                      item_type = "GraphSidecar"
                elif media_objects[0].get('media_type') == "image":
                      item_type = "GraphImage"
                elif media_objects[0].get('media_type') == "video":
                      item_type = "GraphVideo"
                deta_put_instagram(username=username,key_id=id,owner_id=owner_id,item_type=item_type,is_video=is_video,media_url=media_objects,
                            thumbnail_src=thumbnail_src,taken_at_timestamp=taken_at_timestamp,shortcode=shortcode,
                            caption=caption,comments=comments,likes=likes,views=views,location=location,hashtags=hashtags,mentions=mentions)
                for item_media in media_objects:
                  if is_video:
                    media_file_name = await upload_file_by_username(item_media.get('url'), "mp4", shortcode, username)
                  else:
                    media_file_name = await upload_file_by_username(item_media.get('url'), "jpg", shortcode, username)
                  media_list.append(media_file_name)
                  
                for chat_id in chat_ids:
                  if len(media_list) > 1:
                    await send_telegram_group_media(media_list,caption, chat_id,shortcode)
                  elif len(media_list) == 1 :
                    file_name =  media_list[0]
                    await send_telegram_media(file_name,caption, chat_id,shortcode,original_height,original_width)
                  time.sleep(5)
                for filename in media_list:
                  os.remove(filename)
                
       
      return True
    else:
      # return False if the username does not exist
      return False
  except Exception as e:
    print(str(e))
    return None

#210233aecbmsh61a7cefbf2c880cp18192cjsnfa3cbdb526ff
#9695caae8cmsh5842b4bfafdfb1bp1f2bb8jsncb130fa8e8be
async def get_instagram_post_by_shortcode(_shortcode):
  url = f"https://instagram-bulk-profile-scrapper.p.rapidapi.com/clients/api/ig/media_by_id?shortcode={_shortcode}&response_type=feeds"
  headers = {
      'X-RapidAPI-Key': "210233aecbmsh61a7cefbf2c880cp18192cjsnfa3cbdb526ff",
      'X-RapidAPI-Host': "instagram-bulk-profile-scrapper.p.rapidapi.com"
  }
  async with aiohttp.ClientSession() as session:
      async with session.get(url, headers=headers) as resp:
        data = await resp.text()
        print(data)
        if resp.status == 200:
           return data
        else :
          return None
        
async def get_instagram_newpost_by_username(username):
  url = f"https://instagram-bulk-profile-scrapper.p.rapidapi.com/clients/api/ig/ig_profile?ig={username}&response_type=feeds"
  headers = {
      'X-RapidAPI-Key': "210233aecbmsh61a7cefbf2c880cp18192cjsnfa3cbdb526ff",
      'X-RapidAPI-Host': "instagram-bulk-profile-scrapper.p.rapidapi.com"
  }
  async with aiohttp.ClientSession() as session:
      async with session.get(url, headers=headers) as resp:
        data = await resp.text()
        print(data)
        if resp.status == 200:
           return data
        else :
          return None

async def json_to_base_db(username, json_string,_chat_id):
  # Load the JSON data as a Python object
  json_data = json_repair.loads(json_string)
  itercount = 0
  message_response  = await send_message_text_old("📤 Downloading video..."+str(itercount),_chat_id)
  
  messageid = message_response["result"]["message_id"]
  
  
    # Loop through the JSON data
  for item in json_data["collector"]:
    itercount = itercount + 1
    try:
      # Extract the relevant fields from the item
      await edit_message("📤 Downloading video..."+str(itercount),_chat_id,messageid)
      print(itercount)
      id = item.get("id", "")
      owner_id = item.get("owner", {}).get("id", "")
      owner = item.get("owner", {}).get("username", "")
      item_type = item.get("type", "")
      is_video = item.get("is_video", "")
      media_url = item.get("video_url", "") if is_video else item.get("display_url", "")
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
      media_objects = []
      media_object = {
                    'media_type': 'video' if is_video else 'image',
                    'url': media_url,
                    'short_code': shortcode,
                    'height': height,
                    'width': width
                }
      # Add the object to the list
      media_objects.append(media_object)
      # Create a dictionary with the key and other fields
      deta_put_instagram(username=username,key_id=id,owner_id=owner_id,item_type=item_type,is_video=is_video,media_url=media_objects,
                            thumbnail_src=thumbnail_src,taken_at_timestamp=taken_at_timestamp,shortcode=shortcode,
                            caption=caption,comments=comments,likes=likes,views=views,location=location,hashtags=hashtags,mentions=mentions)
      if is_video:
        media_file_name = await upload_file_by_username(media_url, "mp4", shortcode, username)
      else:
        media_file_name = await upload_file_by_username(media_url, "jpg", shortcode, username)
      #await send_telegram_media(media_file_name,caption, _chat_id,shortcode,height,width)
      os.remove(media_file_name)
      #time.sleep(5)                       
    except Exception as e:
        print(e)
        continue
  
  master_data = {
      "key": json_data["id"],
      "username": username,
      "media_count": json_data["count"],
      "Tracking": True,
      "chat_id":_chat_id
  }
  master_db = deta.Base("Instagram_Master")
  master_db.put(master_data)
  
  await delete_message(_chat_id,messageid)

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
          elif item["is_video"] is False :
            itemcount = itemcount + 1
            await upload_file_by_username(item["video_url"], "jpg", item["shortcode"], username)
          
        except Exception as e:
          # send_error("Error in get_all_media_to_drive #Loop items - " + str(e) ,_chat_id)
          print(e)
      return "Success"
    else:
      # return False if the username does not exist
      return "No video items"
  except Exception as e:
    #await send_error("Error in get_all_media_to_drive - " + str(e))
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

async def send_message_video_old(video_file, _caption, _chat_id, _fileName,_height,_width):
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
                    },
                    {
                        "text": "download Post",
                        "url": "https://testwebservice-8vm8.onrender.com/getvideo?url=https://www.instagram.com/reel/"+_fileName
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

async def send_message_text_old(text_message,_chat_id):
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
            
async def send_message_text(text_message,_chat_id):
  try:
    async with Client("my_account", api_id, api_hash,bot_token=BOT_KEY) as pyroapp:
      message = await pyroapp.send_message(chat_id=_chat_id, text=text_message)
      return message
  except Exception as e:
      print(e)
      await send_error("Error in send_message_video - " + str(e), _chat_id)
      return None
  
async def delete_message(chat_id,message_id):
  async with aiohttp.ClientSession() as session: 
    try:
        # Send a message to indicate the start of the upload
        # Delete the download message
      #async with Client("my_account", api_id, api_hash,bot_token=BOT_KEY) as pyroapp: 
        #await pyroapp.delete_messages(chat_id,message.id)
        #return "success"
        # use the deleteMessage method with the chat id and message id
        delete_url = f"{BOT_URL}/deleteMessage"
        payload = {"chat_id": chat_id, "message_id": message_id}
        async with session.post(delete_url, json=payload) as response: # use post method to send message
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

# define a function to edit the error message
async def edit_message(new_message,_chat_id,message_id):
    try:
        async with aiohttp.ClientSession() as session: # use aiohttp instead of requests
            try:
                message_url = f"{BOT_URL}/editMessageText"
                payload = {"text": new_message, "chat_id": _chat_id, "message_id": message_id}
                async with session.post(message_url, json=payload) as response: # use post method to send message
                    resp = await response.json() # get the response data as JSON
                    return resp
            except Exception as e:
                print(e)
                return None
    except Exception as e:
        print(e)

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

# Define a custom progress function
async def progress(current, total, message, start):
    # Calculate the percentage and the elapsed time
    percentage = current * 100 / total
    elapsed_time = round(time.time() - start)

    # Format the progress message
    progress_message = f"📤 Uploading video...\n\n▪️ Progress: {percentage:.1f}%\n▪️ Speed: {format_size(current / elapsed_time)}/s\n▪️ ETA: {round((total - current) / (current / elapsed_time))} seconds"

    # Edit the message with the progress message
    await message.edit(progress_message)

async def instagram_post_handler(chat_id: str, req_shortcode: str):
  try:
    startmessage = await send_message_text("📥 Downloading Post...",chat_id)
    db = deta.Base("Instagram_Master")
    response = db.fetch()# check if the response has any items
    post_exist_in_db = False  # flag to indicate if the video was sent
    media_objects = []
    media_list=[]
    caption = ""

    #If Post Exist in DB
    if response.items:
      # return True if the username exists
      for item in response.items:
        Post_details = await get_post_details_by_shortcode(req_shortcode,item["username"])
        if Post_details is not None:
          for media_objects in Post_details.items:
            media_items = media_objects.get('media_url')
            caption = media_objects.get('caption')
            for media_item in media_items:
              media_shortcode = media_item.get('short_code')
              media_type = media_item.get('media_type')
              original_height = media_item.get('height')
              original_width = media_item.get('width')
              if media_type == "image":
                post_data = await get_post_by_shortcode(media_shortcode,"jpg",media_objects.get('owner'))
                if post_data is not None:
                  media_file_name = f'{media_shortcode}.jpg'
              elif media_type == "video":
                post_data = await get_post_by_shortcode(media_shortcode,"mp4",media_objects.get('owner'))
                if post_data is not None:
                  media_file_name = f'{media_shortcode}.mp4'
              with open(media_file_name, 'wb') as file: # open a file with the same name and type as the video
                  file.write(post_data)
                  
              media_list.append(media_file_name)
              post_exist_in_db = True
                   
    #If Post Not Exist in DB
    if post_exist_in_db is False:
      insta_post = await get_instagram_post_by_shortcode(req_shortcode)
      json_data = json_repair.loads(insta_post)
      for item in json_data:
        for sub_item in item['items']:
          id = sub_item.get("id", "")
          username = sub_item.get("user", {}).get("username", "")
          owner_id = sub_item.get("user", {}).get("pk", "")
          original_height = sub_item.get("original_height", "")
          original_width = sub_item.get("original_width", "")
          caption = sub_item.get("caption", {}).get("text", "")
          product_type = sub_item.get("product_type", "")
          if product_type == "clips":
             is_video = True
          else:
             is_video = False
          shortcode = sub_item.get("code", "")
          taken_at_timestamp = sub_item.get("taken_at", "")
          comments = sub_item.get("comment_count", "")
          likes = sub_item.get("like_count", "")
          views = sub_item.get("view_count", "")
          location = sub_item.get("location", {}).get("name", "")
          thumbnail_src = ""
          hashtags = ""
          mentions = ""
          video_versions = sub_item.get('video_versions', [])
          if(len(video_versions) >= 1):
            media_candidates = video_versions
          else:
            image_versions = sub_item.get('image_versions2', {})
            media_candidates = image_versions.get('candidates', [])
          
          for carousel in sub_item.get('carousel_media', []):
              # Get the list of candidates
              candidates = carousel.get('image_versions2', {}).get('candidates', [])
              # Get the last candidate (1080p image)
              last_candidate = candidates[-1] if candidates else {}
              # Get the URL of the image
              image_url = last_candidate.get('url', '')
              height = last_candidate.get('height', '')
              width = last_candidate.get('width', '')
              # Create an object with media type and URL
              if image_url :
                media_object = {
                    'media_type': 'image' if carousel.get('media_type') == 1 else 'video',
                    'url': image_url,
                    'short_code': carousel.get('shortcode'),
                    'height': height,
                    'width': width
                }
                # Add the object to the list
                media_objects.append(media_object)

          if not media_objects:
            last_candidate = media_candidates[-1]
            image_url = last_candidate.get('url', '')
            print(image_url)
            media_object = {
                    'media_type': 'image' if sub_item.get('media_type') == 1 else 'video',
                    'url': image_url,
                    'short_code': sub_item.get("code", ""),
                    'height': sub_item.get("original_height", ""),
                    'width': sub_item.get("original_width", "")
                }
            media_objects.append(media_object)
      userexist = await is_Username_exist(username,chat_id)
      if(len(media_objects) > 1):
             item_type = "GraphSidecar"
      elif media_objects[0].get('media_type') == "image":
             item_type = "GraphImage"
      elif media_objects[0].get('media_type') == "video":
             item_type = "GraphVideo"

      
      if userexist is not False:
          deta_put_instagram(username=username,key_id=id,owner_id=owner_id,item_type=item_type,is_video=is_video,media_url=media_objects,
                            thumbnail_src=thumbnail_src,taken_at_timestamp=taken_at_timestamp,shortcode=shortcode,
                            caption=caption,comments=comments,likes=likes,views=views,location=location,hashtags=hashtags,mentions=mentions)
          for image in media_objects:
            Image_file = await upload_file_by_username(image.get('url'),"jpg",image.get('short_code'),username)
            media_list.append(Image_file)
      else:
         deta_put_instagram(username="others",key_id=id,owner_id=owner_id,item_type=item_type,is_video=is_video,media_url=media_objects,
                            thumbnail_src=thumbnail_src,taken_at_timestamp=taken_at_timestamp,shortcode=shortcode,
                            caption=caption,comments=comments,likes=likes,views=views,location=location,hashtags=hashtags,mentions=mentions)
         for image in media_objects:
          if image.get('media_type') == "image":
            Image_file = await upload_file_by_username(image.get('url'),"jpg",image.get('short_code'),"others")
            media_list.append(Image_file)
          elif image.get('media_type') == "video":
            video_file = await upload_file_by_username(image.get('url'),"mp4",image.get('short_code'),"others")
            media_list.append(video_file)

    if len(media_list) > 1:
      await send_telegram_group_media(media_list,caption, chat_id,req_shortcode)
    elif len(media_list) == 1 :
      file_name =  media_list[0]
      await send_telegram_media(file_name,caption, chat_id,req_shortcode,original_height,original_width)
       #await delete_message(chat_id,startmessage)
    return True
  except Exception as e:
    await send_error(str(e),chat_id)
    return None
  finally:
     for filename in media_list:
      os.remove(filename)
     #await delete_message(chat_id,startmessage)

def deta_put_instagram(username,key_id,owner_id,item_type,is_video,media_url,thumbnail_src,taken_at_timestamp,shortcode,
                       caption,comments,likes,views,location,hashtags,mentions ):
    try:
      user_db = deta.Base(username)
      user_db.put(data = {
          "key": key_id,
          "owner_id": owner_id,
          "owner": username,
          "type": item_type,
          "is_video": is_video,
          "media_url": media_url,
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
          })
      return True
    except:
      return False

async def get_video_Exist_DB(shortcode):
  try:
    db = deta.Base("Instagram_Master")
    response = db.fetch()# check if the response has any items
    if response.items:
      # return True if the username exists
      for item in response.items:
        video_file = await get_post_by_shortcode(shortcode,"mp4",item["username"])
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

async def stream_video_from_file(file_path: str):
    # This is an async generator function that yields chunks of the video file
    chunk_size = 1024 * 1024  # Chunk size of 1MB
    # Open the file in binary mode
    with open(file_path, 'rb') as f:
        # Read the file in chunks
        while True:
            data = f.read(chunk_size)
            # Check if the file has ended
            if not data:
                break
            # Yield the chunk of data
            yield data

async def get_profile_by_username(username,_chat_id):
  url = f"https://instagram-bulk-profile-scrapper.p.rapidapi.com/clients/api/ig/ig_profile?ig={username}&response_type=short&corsEnabled=false"
  headers = {
      'X-RapidAPI-Key': "210233aecbmsh61a7cefbf2c880cp18192cjsnfa3cbdb526ff",
      'X-RapidAPI-Host': "instagram-bulk-profile-scrapper.p.rapidapi.com"
  }
  async with aiohttp.ClientSession() as session:
      async with session.get(url, headers=headers) as resp:
        data = await resp.text()
        print(data)
        if resp.status == 200:
           json_data = json_repair.loads(data)
           for item in json_data:
              profile_hd = item.get('profile_pic_url_hd')
              user_id = item.get('pk')
              username = item.get('username')
              media_count = item.get('media_count')
              keyboard = InlineKeyboardMarkup([
                  [ # Row 1 button
                      InlineKeyboardButton(
                          text=f'Get Media : {media_count}',
                          callback_data=f'get_media_{user_id}'
                      )
                  ]
              ])
              async with Client("my_account", api_id, api_hash,bot_token=BOT_KEY) as pyroapp:
                 await pyroapp.send_photo(chat_id  = _chat_id, photo = profile_hd,caption = username,reply_markup=keyboard)
                 
           return data
        else :
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

@app.get("/echo")
async def echo():
    return "Server is Live"

@app.get("/SaveKey")
def SaveKey():
  rapid_db = deta.Base("Rapid_API_Keys")
  rapid_db.put(data = {
    "key": "210233aecbmsh61a7cefbf2c880cp18192cjsnfa3cbdb526ff",
    "Account":"johnnikki272@gmail.com",
    "Rapid-api_Name":"IG Data,Instagram Bulk Profile Scrapper",
    "api_name": "Instagram-Data",
    "is_Primary" : True})
  rapid_db.put(data = {
    "key": "90fe634f95mshab51bdbbb21aab9p16e278jsndb3368361c77",
    "Account":"johnnikki271@gmail.com",
    "Rapid-api_Name":"IG Data,Instagram Bulk Profile Scrapper",
    "api_name": "Instagram-Data",
    "is_Primary" : False})
  rapid_db.put(
      data={
          "key": "9695caae8cmsh5842b4bfafdfb1bp1f2bb8jsncb130fa8e8be",
          "Account":"johnnikki271@outlook.com",
          "Rapid-api_Name":"IG Data,Instagram Bulk Profile Scrapper",
          "api_name": "Instagram-Data",
          "is_Primary": False
      })
  rapid_db.put(
      data={
          "key": "9fc5d92744mshc1c1266651fa9b9p117e6djsna8fa34ea259b",
          "Account":"johnnikki272@outlook.com",
          "Rapid-api_Name":"IG Data,Instagram Bulk Profile Scrapper",
          "api_name": "Instagram-Data",
          "is_Primary": False
      })
  return "Success"

@app.post("/open")
async def http_handler(request: Request, background_tasks: BackgroundTasks):
    """Handle the incoming messages from Telegram"""
    try:
        incoming_data = await request.json() # parse the request data as JSON
        callback_data = incoming_data.get("callback_query")
        if callback_data:
          prompt = callback_data.get("data") # get the text from the message
          chat_id = callback_data["message"]["chat"]["id"] # get the chat id from the message
        else:
          prompt = incoming_data.get("message", {}).get("text", "No text found") # get the text from the message
          chat_id = incoming_data["message"]["chat"]["id"] # get the chat id from the message
    except Exception as e:
        print(e)
        return None
    
    #if "message" not in incoming_data:
        #print(incoming_data)
        #return await send_error(None, "Unknown error, lol, handling coming soon")
    if "get_media_" in prompt:
       userid = prompt.split("get_media_")[1]
       background_tasks.add_task(get_all_instagram_posts_rotateKey, userid=userid, count=50,_chat_id=chat_id)
       return
    
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
          response_text = video_shortcode
          await send_message_text(response_text,chat_id)
          background_tasks.add_task(instagram_post_handler, chat_id, video_shortcode)
      elif is_Instagram_photo(prompt):
          photo_shortcode = is_Instagram_photo(prompt)
          response_text = "This is a photo URL - " + photo_shortcode
          await send_message_text(response_text,chat_id)
          background_tasks.add_task(instagram_post_handler, chat_id, photo_shortcode)
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
            #background_tasks.add_task(get_all_instagram_posts_rotateKey, username=profile_username, count=50,_chat_id=chat_id)
            background_tasks.add_task(get_profile_by_username, username=profile_username,_chat_id=chat_id)
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
             insta_post = await get_instagram_post_by_shortcode(shortcode)
             json_data = json_repair.loads(insta_post)
             for item in json_data:
              for sub_item in item['items']:
                video_versions = sub_item.get('video_versions', [])
                for video_version in video_versions:
                  video_url = video_version.get('url', '')
             await upload_file_by_username(video_url,"mp4",shortcode,"others")
             video_file = await get_video_Exist_DB(shortcode)
             if(video_file is not None):
               return StreamingResponse(stream_video(video_file), media_type="video/mp4")
        else :
           return "Url is not Valid !! "
    else:
        return "Missing parameters in query string"

@app.get("/getupdates")
async def getupdates(request: Request, background_tasks: BackgroundTasks):
   background_tasks.add_task(get_update_post_handler)
   return "Background Task Started"



if __name__ == '__main__':
    uvicorn.run(app)
