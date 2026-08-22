import asyncio
import os
import sys
import traceback
import pyaudio
import csv
import struct
import socket
import math
import random
import time
from datetime import datetime
import speech_recognition as sr
from dotenv import load_dotenv
from google import genai
from google.genai import types

# Conditional ctypes import for Windows mouse simulation
if sys.platform == "win32":
    import ctypes

# Load environment variables
load_dotenv()

# Reconfigure stdout/stderr to avoid encoding errors on Windows when printing emojis
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')
        sys.stderr.reconfigure(encoding='utf-8', errors='backslashreplace')
    except AttributeError:
        pass

# Configuration
API_KEY = os.environ.get("GEMINI_API_KEY")
MODEL_ID = "models/gemini-3.1-flash-live-preview"

# OSC Settings
OSC_IP = os.getenv("OSC_IP", "127.0.0.1")
OSC_PORT = int(os.getenv("OSC_PORT", "9000"))
HEAD_MOVEMENT_ENABLED = os.getenv("HEAD_MOVEMENT_ENABLED", "True").lower() == "true"
HEAD_MOVEMENT_MODE = os.getenv("HEAD_MOVEMENT_MODE", "tracker").lower()
HEAD_PITCH_PARAMETER = os.getenv("HEAD_PITCH_PARAMETER", "/avatar/parameters/HeadPitch")
HEAD_YAW_PARAMETER = os.getenv("HEAD_YAW_PARAMETER", "/avatar/parameters/HeadYaw")
HEAD_ROLL_PARAMETER = os.getenv("HEAD_ROLL_PARAMETER", "/avatar/parameters/HeadRoll")
LOOK_INPUT_GAIN = float(os.getenv("LOOK_INPUT_GAIN", "0.02"))
LOOK_DEADZONE = float(os.getenv("LOOK_DEADZONE", "0.08"))

# Talk Indicator Settings
TALK_INDICATOR_MOUSE1_ENABLED = os.getenv("TALK_INDICATOR_MOUSE1_ENABLED", "True").lower() == "true"
TALK_INDICATOR_MODE = os.getenv("TALK_INDICATOR_MODE", "osc").lower()  # "osc", "windows_mouse", or "windows_keyboard"
TALK_INDICATOR_ACTION_TYPE = os.getenv("TALK_INDICATOR_ACTION_TYPE", "hold").lower()  # "hold" or "click"
TALK_INDICATOR_OSC_ADDRESS = os.getenv("TALK_INDICATOR_OSC_ADDRESS", "/input/Use")
TALK_INDICATOR_DEBOUNCE_DELAY = float(os.getenv("TALK_INDICATOR_DEBOUNCE_DELAY", "0.4"))

def _parse_key_code():
    val = os.getenv("TALK_INDICATOR_KEY_CODE", "0x45").strip()
    try:
        if val.lower().startswith("0x"):
            return int(val, 16)
        else:
            return int(val)
    except ValueError:
        return 0x45  # Default to 'E' key (0x45)
TALK_INDICATOR_KEY_CODE = _parse_key_code()

def simulate_mouse_1(pressed: bool):
    """Simulates a Windows left mouse button event (down or up)."""
    if sys.platform != "win32":
        return
    # MOUSEEVENTF_LEFTDOWN = 0x0002, MOUSEEVENTF_LEFTUP = 0x0004
    flags = 0x0002 if pressed else 0x0004
    try:
        ctypes.windll.user32.mouse_event(flags, 0, 0, 0, 0)
    except Exception as e:
        print(f"Failed to simulate mouse click: {e}")

def simulate_key(key_code: int, pressed: bool):
    """Simulates a Windows keyboard event (down or up)."""
    if sys.platform != "win32":
        return
    # KEYEVENTF_KEYUP = 0x0002
    flags = 0 if pressed else 0x0002
    try:
        ctypes.windll.user32.keybd_event(key_code, 0, flags, 0)
    except Exception as e:
        print(f"Failed to simulate key event for key code {hex(key_code)}: {e}")

# Head movement angle limits (in degrees) for normalization in parameter mode
HEAD_LIMIT_PITCH = 20.0
HEAD_LIMIT_YAW = 30.0
HEAD_LIMIT_ROLL = 15.0

def make_osc_message(address: str, types: str, *args):
    """Serializes a standard OSC message to bytes."""
    def pad_string(s):
        b = s.encode('utf-8') + b'\x00'
        padding = (4 - (len(b) % 4)) % 4
        return b + (b'\x00' * padding)

    msg = pad_string(address)
    msg += pad_string(',' + types)

    for t, val in zip(types, args):
        if t == 'f':
            msg += struct.pack('>f', float(val))
        elif t == 'i':
            msg += struct.pack('>i', int(val))
        elif t == 's':
            msg += pad_string(val)
    return msg


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

def load_system_prompt():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    filepath = os.path.join(script_dir, "prompt.txt")
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

CONFIG = types.LiveConnectConfig(
    response_modalities=["AUDIO"],
    system_instruction=types.Content(
        parts=[types.Part.from_text(text=SYSTEM_PROMPT)]
    ),
    output_audio_transcription=types.AudioTranscriptionConfig(),
    speech_config=types.SpeechConfig(
        voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                voice_name="Autonoe"
            )
        )
    )
)

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
        self.is_speaking = False

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
                                        if not turn_text:
                                            print("Gemini: ", end="", flush=True)
                                        try:
                                            print(part.text, end="", flush=True)
                                        except Exception:
                                            pass
                                        turn_text += part.text

                            # Retrieve text transcript if audio transcription is enabled
                            if response.server_content.output_transcription:
                                text = response.server_content.output_transcription.text
                                if text:
                                    if not turn_text:
                                        print("Gemini: ", end="", flush=True)
                                    try:
                                        print(text, end="", flush=True)
                                    except Exception:
                                        pass
                                    turn_text += text
                                        
                            if response.server_content.turn_complete:
                                if turn_text.strip():
                                    print() # Newline after completed turn transcript
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
                self.is_speaking = True
                try:
                    await asyncio.to_thread(stream.write, bytestream)
                except Exception:
                    pass
                if self.audio_in_queue.empty():
                    self.is_speaking = False

    async def monitor_speaking(self):
        """Monitors speaking state and sends inputs (OSC, mouse, or keyboard) to VRChat."""
        if not TALK_INDICATOR_MOUSE1_ENABLED:
            return

        print(f"Starting Talk Indicator monitor. Mode: {TALK_INDICATOR_MODE.upper()}, Action: {TALK_INDICATOR_ACTION_TYPE.upper()}")

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        was_speaking = False
        last_time_speaking = 0.0

        def set_input_state(pressed: bool):
            try:
                if TALK_INDICATOR_MODE == "osc":
                    val = 1 if pressed else 0
                    msg = make_osc_message(TALK_INDICATOR_OSC_ADDRESS, "i", val)
                    sock.sendto(msg, (OSC_IP, OSC_PORT))
                elif TALK_INDICATOR_MODE == "windows_mouse":
                    simulate_mouse_1(pressed)
                elif TALK_INDICATOR_MODE == "windows_keyboard":
                    simulate_key(TALK_INDICATOR_KEY_CODE, pressed)
            except Exception as e:
                print(f"[Talk Indicator] Error setting input state: {e}")

        try:
            while True:
                now = time.time()
                if self.is_speaking:
                    last_time_speaking = now
                
                is_currently_speaking = (now - last_time_speaking) < TALK_INDICATOR_DEBOUNCE_DELAY
                
                if is_currently_speaking != was_speaking:
                    was_speaking = is_currently_speaking
                    print(f"[Talk Indicator] Speaking state changed: {is_currently_speaking}")
                    
                    if TALK_INDICATOR_ACTION_TYPE == "hold":
                        set_input_state(is_currently_speaking)
                    elif TALK_INDICATOR_ACTION_TYPE == "click":
                        # Trigger a quick click/tap on transition (press and release)
                        async def perform_click():
                            set_input_state(True)
                            await asyncio.sleep(0.1)
                            set_input_state(False)
                        asyncio.create_task(perform_click())
                    
                await asyncio.sleep(0.02)
        finally:
            # Ensure we release the button/key on shutdown
            try:
                set_input_state(False)
            except Exception:
                pass
            print("[Talk Indicator] Released and stopped.")

    async def animate_head(self):
        """Generates and sends smooth, lifelike head movements to VRChat via OSC UDP packets."""
        if not HEAD_MOVEMENT_ENABLED:
            print("Head movement is disabled in settings.")
            return

        print(f"Starting Head Movement. Sending to {OSC_IP}:{OSC_PORT} via {HEAD_MOVEMENT_MODE.upper()} mode.")

        # Set up socket for UDP
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # Base loop control
        interval = 0.04 # 25 Hz (every 40ms)
        
        # State variables for pauses in the Figure 8 idle movement
        virtual_time = 0.0
        time_speed = 1.0
        target_time_speed = 1.0
        last_pause_change = time.time()
        pause_change_interval = random.uniform(5.0, 10.0) # Move for 5-10s initially
        is_paused = False

        try:
            while True:
                try:
                    now = time.time()

                    # --- 1. HANDLE IDLE MOVE PAUSES ---
                    # Periodically decide to pause or resume the idle movement
                    if now - last_pause_change > pause_change_interval:
                        is_paused = not is_paused
                        last_pause_change = now
                        if is_paused:
                            target_time_speed = 0.0
                            pause_change_interval = random.uniform(2.0, 5.0) # Pause for 2-5s
                        else:
                            target_time_speed = 1.0
                            pause_change_interval = random.uniform(6.0, 12.0) # Move for 6-12s
                    
                    # Smoothly lerp time speed to ease-in/ease-out of pauses
                    time_speed += (target_time_speed - time_speed) * 0.08
                    
                    # Update virtual time
                    virtual_time += interval * time_speed

                    # --- 2. IDLE MOVEMENT: FIGURE 8 ---
                    # Slow, smooth lemniscate of Gerono path for yaw and pitch
                    # Yaw period = 15s, pitch period = 7.5s (two loops)
                    omega = 2.0 * math.pi / 15.0
                    amp_yaw = 1.8
                    amp_pitch = 0.8
                    amp_roll = 0.5

                    # Absolute angles (for tracker/parameters modes) using virtual_time
                    pos_8_yaw = amp_yaw * math.sin(virtual_time * omega)
                    pos_8_pitch = amp_pitch * math.sin(virtual_time * 2.0 * omega)
                    pos_8_roll = amp_roll * math.sin(virtual_time * omega + 0.5)

                    # Derivatives (velocity in deg/sec for input mode) scaled by time_speed (chain rule)
                    vel_8_yaw = amp_yaw * omega * math.cos(virtual_time * omega) * time_speed
                    vel_8_pitch = amp_pitch * (2.0 * omega) * math.cos(virtual_time * 2.0 * omega) * time_speed

                    # --- 3. COMBINE AND SEND ---
                    if HEAD_MOVEMENT_MODE == "tracker":
                        final_pitch = pos_8_pitch
                        final_yaw = pos_8_yaw
                        final_roll = pos_8_roll
                        msg = make_osc_message("/tracking/trackers/head/rotation", "fff", final_pitch, final_yaw, final_roll)
                        sock.sendto(msg, (OSC_IP, OSC_PORT))

                    elif HEAD_MOVEMENT_MODE == "parameters":
                        final_pitch = pos_8_pitch
                        final_yaw = pos_8_yaw
                        final_roll = pos_8_roll

                        # Clamp inputs to the defined safety thresholds
                        norm_pitch = max(-1.0, min(1.0, final_pitch / HEAD_LIMIT_PITCH))
                        norm_yaw = max(-1.0, min(1.0, final_yaw / HEAD_LIMIT_YAW))
                        norm_roll = max(-1.0, min(1.0, final_roll / HEAD_LIMIT_ROLL))

                        msg_p = make_osc_message(HEAD_PITCH_PARAMETER, "f", norm_pitch)
                        msg_y = make_osc_message(HEAD_YAW_PARAMETER, "f", norm_yaw)
                        msg_r = make_osc_message(HEAD_ROLL_PARAMETER, "f", norm_roll)

                        sock.sendto(msg_p, (OSC_IP, OSC_PORT))
                        sock.sendto(msg_y, (OSC_IP, OSC_PORT))
                        sock.sendto(msg_r, (OSC_IP, OSC_PORT))

                    elif HEAD_MOVEMENT_MODE == "input":
                        total_vel_pitch = vel_8_pitch
                        total_vel_yaw = vel_8_yaw

                        # Scale by LOOK_INPUT_GAIN
                        look_vertical = total_vel_pitch * LOOK_INPUT_GAIN
                        look_horizontal = total_vel_yaw * LOOK_INPUT_GAIN

                        # Apply deadzone compensation
                        def compensate(val, deadzone):
                            if abs(val) < 1e-4:
                                return 0.0
                            if val > 0:
                                return deadzone + val * (1.0 - deadzone)
                            else:
                                return -deadzone + val * (1.0 - deadzone)

                        look_vertical = compensate(look_vertical, LOOK_DEADZONE)
                        look_horizontal = compensate(look_horizontal, LOOK_DEADZONE)

                        look_vertical = max(-1.0, min(1.0, look_vertical))
                        look_horizontal = max(-1.0, min(1.0, look_horizontal))

                        msg_y = make_osc_message("/input/LookHorizontal", "f", look_horizontal)
                        msg_p = make_osc_message("/input/LookVertical", "f", look_vertical)

                        sock.sendto(msg_y, (OSC_IP, OSC_PORT))
                        sock.sendto(msg_p, (OSC_IP, OSC_PORT))

                except Exception as e:
                    pass

                await asyncio.sleep(interval)
        finally:
            if HEAD_MOVEMENT_MODE == "input":
                try:
                    # Final emergency reset of Look inputs to stop any movement
                    msg_y = make_osc_message("/input/LookHorizontal", "f", 0.0)
                    msg_p = make_osc_message("/input/LookVertical", "f", 0.0)
                    sock.sendto(msg_y, (OSC_IP, OSC_PORT))
                    sock.sendto(msg_p, (OSC_IP, OSC_PORT))
                    print("Reset OSC Look inputs on task completion/cancellation.")
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
                    tg.create_task(self.animate_head())
                    tg.create_task(self.monitor_speaking())

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
        # Emergency reset of Look inputs to stop any movement
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.sendto(b'/input/LookHorizontal\x00\x00\x00,f\x00\x00\x00\x00\x00\x00', (OSC_IP, OSC_PORT))
            s.sendto(b'/input/LookVertical\x00\x00\x00\x00\x00,f\x00\x00\x00\x00\x00\x00', (OSC_IP, OSC_PORT))
            print("Look inputs successfully reset to 0.0.")
        except Exception:
            pass
