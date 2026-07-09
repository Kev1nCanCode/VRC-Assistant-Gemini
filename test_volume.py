import pyaudio
import audioop

p = pyaudio.PyAudio()
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
CHUNK = 512

print("Opening stream on device 2...")
stream = p.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, input_device_index=2, frames_per_buffer=CHUNK)

print("Listening for 3 seconds...")
rms_values = []
for _ in range(0, int(RATE / CHUNK * 3)):
    data = stream.read(CHUNK, exception_on_overflow=False)
    rms_values.append(audioop.rms(data, 2))

stream.stop_stream()
stream.close()
p.terminate()

avg_rms = sum(rms_values) / len(rms_values)
max_rms = max(rms_values)

print(f"Avg RMS Volume: {avg_rms}")
print(f"Max RMS Volume: {max_rms}")
if max_rms == 0:
    print("WARNING: Audio is completely silent! (Zero data)")
