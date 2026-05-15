# Gemini Live VRChat Assistant

A simplified, low-latency VRChat AI assistant powered by the Gemini Multimodal Live API.

## Features
- **Real-time Voice Conversation:** Talk to Gemini naturally with extremely low latency.
- **Automated Lip-Sync:** Since the AI's voice is routed to your VRChat microphone, VRChat automatically handles your avatar's mouth movements (visemes).

## Prerequisites
1. **Gemini API Key:** Obtain one from [Google AI Studio](https://aistudio.google.com/).
2. **Virtual Audio Cable:**
   - Install [VB-Audio Virtual Cable](https://vb-audio.com/Cable/) (or similar).
   - This allows the Python script to send Gemini's voice into VRChat.
3. **Python 3.10+**

## Setup
1. Clone this project.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Configure your `.env` file:
   ```env
   GEMINI_API_KEY=your_api_key_here
   INPUT_DEVICE_NAME=MacBook Air-Mikrofon
   OUTPUT_DEVICE_NAME=CABLE Input
   ```
   *Note: Use `INPUT_DEVICE_NAME` to specify your physical mic and `OUTPUT_DEVICE_NAME` for the Virtual Audio Cable (e.g., "CABLE Input").*

## VRChat Configuration
1. Open VRChat.
2. Go to **Settings > Audio**.
3. Set your **Microphone** to **CABLE Output** (VB-Audio Virtual Cable).

## Running the Bot
```bash
python bot.py
```
Speak into your microphone, and Gemini will respond through the Virtual Audio Cable into VRChat.
