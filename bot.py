import asyncio
import os
import traceback
import pyaudio
import csv
from datetime import datetime
import speech_recognition as sr
from dotenv import load_dotenv
from google import genai
from google.genai import types

# Load environment variables
load_dotenv()

# Configuration
API_KEY = os.environ.get("GEMINI_API_KEY")
MODEL_ID = "models/gemini-3.1-flash-live-preview"

# Audio Settings
FORMAT = pyaudio.paInt16
CHANNELS = 1
INPUT_RATE = 16000
OUTPUT_RATE = 24000
CHUNK_SIZE = 512

client = genai.Client(
    http_options={"api_version": "v1alpha"},
    api_key=API_KEY,
)

def load_system_prompt(filepath="prompt.txt"):
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        default_prompt = "You are a helpful and friendly VRChat assistant. Speak naturally, be conversational, and keep your responses concise."
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(default_prompt)
        except Exception as e:
            print(f"Warning: Could not create {filepath}: {e}")
        return default_prompt

SYSTEM_PROMPT = load_system_prompt()

CONFIG = {
    "response_modalities": ["AUDIO"],
    "system_instruction": SYSTEM_PROMPT
}

pya = pyaudio.PyAudio()

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

def log_to_csv(speaker, text):
    """Logs the conversation to a CSV file."""
    file_exists = os.path.isfile("chat_history.csv")
    with open("chat_history.csv", mode='a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["Timestamp", "Speaker", "Message"])
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        writer.writerow([timestamp, speaker, text])

class VRChatBot:
    def __init__(self):
        self.audio_in_queue = None
        self.out_queue = None
        self.session = None
        self.audio_stream = None

        input_name = os.getenv("INPUT_DEVICE_NAME", "CABLE-B Output")
        output_name = os.getenv("OUTPUT_DEVICE_NAME", "CABLE-A Input")

        self.input_device_index = get_device_index(pya, input_name, is_input=True)
        self.output_device_index = get_device_index(pya, output_name, is_input=False)

        print(f"Using Input Device: {self.input_device_index}")
        print(f"Using Output Device: {self.output_device_index}")
        
        # Setup SpeechRecognition
        self.recognizer = sr.Recognizer()

    def _on_speech_recognized(self, recognizer, audio):
        """Callback for when user finishes speaking."""
        try:
            # Using the free Google Web Speech API
            text = recognizer.recognize_google(audio)
            print(f"User (Recognized): {text}")
            log_to_csv("User", text)
        except sr.UnknownValueError:
            pass # Could not understand audio
        except sr.RequestError as e:
            print(f"SpeechRecognition Error: {e}")

    async def listen_audio(self):
        """Captures audio from VRChat and puts it in the output queue."""
        self.audio_stream = await asyncio.to_thread(
            pya.open,
            format=FORMAT,
            channels=CHANNELS,
            rate=INPUT_RATE,
            input=True,
            input_device_index=self.input_device_index,
            frames_per_buffer=CHUNK_SIZE,
        )
        kwargs = {"exception_on_overflow": False}
        while True:
            data = await asyncio.to_thread(self.audio_stream.read, CHUNK_SIZE, **kwargs)
            if self.out_queue is not None:
                await self.out_queue.put({"data": data, "mime_type": f"audio/pcm;rate={INPUT_RATE}"})

    async def send_realtime(self):
        """Takes audio from the output queue and sends it to Gemini."""
        while True:
            if self.out_queue is not None:
                msg = await self.out_queue.get()
                if self.session is not None:
                    await self.session.send_realtime_input(
                        audio=types.Blob(data=msg["data"], mime_type=msg["mime_type"])
                    )

    async def receive_audio(self):
        """Receives audio from Gemini turn by turn."""
        while True:
            if self.session is not None:
                turn = self.session.receive()
                turn_text = ""
                try:
                    async for response in turn:
                        if response.server_content:
                            if response.server_content.model_turn:
                                for part in response.server_content.model_turn.parts:
                                    if part.inline_data:
                                        self.audio_in_queue.put_nowait(part.inline_data.data)
                                    if part.text:
                                        print(f"Gemini: {part.text}")
                                        turn_text += part.text
                                        
                            if response.server_content.turn_complete:
                                if turn_text.strip():
                                    log_to_csv("Gemini", turn_text.strip())
                                    turn_text = ""
                                
                                # Turn is complete or model was interrupted!
                                while not self.audio_in_queue.empty():
                                    self.audio_in_queue.get_nowait()
                                    
                except Exception as e:
                    print(f"Receive Error: {e}")
                    await asyncio.sleep(1)

    async def play_audio(self):
        """Takes audio from the input queue and plays it into VRChat."""
        stream = await asyncio.to_thread(
            pya.open,
            format=FORMAT,
            channels=CHANNELS,
            rate=OUTPUT_RATE,
            output=True,
            output_device_index=self.output_device_index,
            frames_per_buffer=CHUNK_SIZE
        )
        while True:
            if self.audio_in_queue is not None:
                bytestream = await self.audio_in_queue.get()
                try:
                    await asyncio.to_thread(stream.write, bytestream)
                except Exception:
                    pass

    async def run(self):
        if not API_KEY:
            print("Error: GEMINI_API_KEY not found in .env file.")
            return
            
        print("Calibrating background noise for SpeechRecognition...")
        mic = sr.Microphone(device_index=self.input_device_index)
        with mic as source:
            self.recognizer.adjust_for_ambient_noise(source)
        stop_listening = self.recognizer.listen_in_background(mic, self._on_speech_recognized)
        print("SpeechRecognition is active and listening.")

        while True:
            try:
                print("Connecting to Gemini Live API...")
                async with (
                    client.aio.live.connect(model=MODEL_ID, config=CONFIG) as session,
                    asyncio.TaskGroup() as tg,
                ):
                    print("Connected to Gemini Live API!")
                    self.session = session
                    self.audio_in_queue = asyncio.Queue()
                    self.out_queue = asyncio.Queue(maxsize=10)

                    tg.create_task(self.send_realtime())
                    tg.create_task(self.listen_audio())
                    tg.create_task(self.receive_audio())
                    tg.create_task(self.play_audio())

            except asyncio.CancelledError:
                break
            except ExceptionGroup as EG:
                if self.audio_stream is not None:
                    self.audio_stream.stop_stream()
                traceback.print_exception(EG)
                print("Connection closed. Reconnecting in 2 seconds...")
                await asyncio.sleep(2)
            except Exception as e:
                print(f"Connection Failed: {e}. Retrying in 2 seconds...")
                await asyncio.sleep(2)
                
        # Clean up SR thread if we exit completely
        stop_listening(wait_for_stop=False)

if __name__ == "__main__":
    bot = VRChatBot()
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        print("\nBot stopped by user.")
