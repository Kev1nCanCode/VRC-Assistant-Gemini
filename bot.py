import asyncio
import os
import sys
import pyaudio
from dotenv import load_dotenv
from google import genai
from google.genai import types

# Load environment variables
load_dotenv()

# Configuration
API_KEY = os.getenv("GEMINI_API_KEY")
MODEL_ID = "models/gemini-3.1-flash-live-preview"  # Live API model

# Audio Settings
FORMAT = pyaudio.paInt16
CHANNELS = 1
INPUT_RATE = 16000  # Gemini Live API expects 16kHz for input
OUTPUT_RATE = 24000 # Gemini Live API expects 24kHz for output
CHUNK = 512

def get_device_index(p, name_substring, is_input=True):
    """Finds a device index by name substring."""
    for i in range(p.get_device_count()):
        dev = p.get_device_info_by_index(i)
        if name_substring.lower() in dev['name'].lower():
            if is_input and dev['maxInputChannels'] > 0:
                return i
            if not is_input and dev['maxOutputChannels'] > 0:
                return i
    return None

async def run_bot():
    if not API_KEY:
        print("Error: GEMINI_API_KEY not found in .env file.")
        return

    # Initialize PyAudio
    p = pyaudio.PyAudio()

    # Device Selection
    # Preference: ENV > Hardcoded Name > Default
    input_name = os.getenv("INPUT_DEVICE_NAME", "MacBook Air-Mikrofon")
    output_name = os.getenv("OUTPUT_DEVICE_NAME", "MacBook Air-Lautsprecher")

    input_device_index = get_device_index(p, input_name, is_input=True)
    output_device_index = get_device_index(p, output_name, is_input=False)

    print(f"Using Input Device: {input_device_index} (Default if None)")
    print(f"Using Output Device: {output_device_index} (Default if None)")

    # Initialize Gemini Client
    client = genai.Client(api_key=API_KEY, http_options={'api_version': 'v1alpha'})
    
    config = {"response_modalities": ["AUDIO"]}

    async with client.aio.live.connect(model=MODEL_ID, config=config) as session:
        print("Connected to Gemini Live API!")

        # Setup PyAudio Streams
        input_stream = p.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=INPUT_RATE,
            input=True,
            input_device_index=input_device_index,
            frames_per_buffer=CHUNK
        )

        output_stream = p.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=OUTPUT_RATE,
            output=True,
            output_device_index=output_device_index,
            frames_per_buffer=CHUNK
        )

        async def send_audio():
            """Continuously captures audio and sends it to Gemini."""
            try:
                while True:
                    data = await asyncio.to_thread(input_stream.read, CHUNK, exception_on_overflow=False)
                    await session.send_realtime_input(
                        audio=types.Blob(data=data, mime_type=f"audio/pcm;rate={INPUT_RATE}")
                    )
            except Exception as e:
                print(f"Send Error: {e}")

        async def receive_audio():
            """Continuously receives audio from Gemini and plays it back."""
            try:
                async for message in session.receive():
                    if message.server_content and message.server_content.model_turn:
                        for part in message.server_content.model_turn.parts:
                            if part.inline_data:
                                await asyncio.to_thread(output_stream.write, part.inline_data.data)
                            if part.text:
                                print(f"Gemini: {part.text}")
            except Exception as e:
                print(f"Receive Error: {e}")

        # Run send and receive concurrently
        await asyncio.gather(send_audio(), receive_audio())

        # Cleanup
        input_stream.stop_stream()
        input_stream.close()
        output_stream.stop_stream()
        output_stream.close()
        p.terminate()

if __name__ == "__main__":
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        print("\nBot stopped by user.")
