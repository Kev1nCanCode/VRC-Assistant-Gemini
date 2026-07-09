import asyncio
import pyaudio
import speech_recognition as sr
import os

async def main():
    p = pyaudio.PyAudio()
    # Assume default input device for test
    input_stream = p.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True, frames_per_buffer=512)
    print("PyAudio stream opened successfully.")
    
    r = sr.Recognizer()
    mic = sr.Microphone()
    with mic as source:
        print("SpeechRecognition mic opened successfully.")
    
    input_stream.close()
    p.terminate()

asyncio.run(main())
