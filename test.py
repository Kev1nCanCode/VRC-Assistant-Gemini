import asyncio
import os
import dotenv
from google import genai
from google.genai import types

dotenv.load_dotenv()

async def run():
    client = genai.Client(http_options={'api_version':'v1alpha'})
    config = {"response_modalities": ["AUDIO"]}
    try:
        async with client.aio.live.connect(model='models/gemini-3.1-flash-live-preview', config=config) as session:
            print('connected')
            await asyncio.sleep(5)
            print('done')
    except Exception as e:
        print(f"Error: {e}")

asyncio.run(run())
