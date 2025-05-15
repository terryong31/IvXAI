# IvXAI

**IvXAI** is a stealthy AI-powered overlay tool built for screen and audio input during interviews or technical assessments. It listens, sees, and responds using OpenAI APIs and a local Whisper speech model — all while staying hidden from screen recording and sharing tools.

---

## 🚀 Features

- 🎤 **Audio to Smart Reply**
  - Press `Ctrl + Alt + R` to record 15 seconds of audio.
  - Transcribes speech using **faster-whisper**.
  - Responds intelligently with **GPT-4o-mini** in Malaysian conversational tone.
  - Supports both English and Malay inputs.

- 🖼️ **Screen Capture & Explanation**
  - Press `Ctrl + Alt + Z` to capture the screen.
  - Sends image to **GPT-4o** for analysis.
  - If coding questions (e.g., LeetCode) are detected, it replies with a Python solution.

- 🫥 **Overlay Hidden from Screen Sharing**
  - Uses `SetWindowDisplayAffinity` and Windows API to hide the GUI from being captured in screen recordings or sharing.
  - Overlay stays click-through and semi-transparent.

- 🧠 **Smart Caching**
  - Avoids duplicate API calls with a simple `.cache.json` file.
  - Keeps interaction logs in `.interview_log.txt`.

- 🎛️ **Hotkeys & Navigation**
  - `Ctrl + Alt + Z` — Capture screen  
  - `Ctrl + Alt + R` — Record audio  
  - `Ctrl + Alt + Q` — Quit app  
  - `Ctrl + Alt + M` — Hide/Show overlay  
  - `Ctrl + Alt + W/A/S/D` — Move window  
  - `Ctrl + Alt + U/J` — Scroll

---

## 🧪 Tech Stack

- Python 3.10+
- OpenAI API (GPT-4o, GPT-4o-mini)
- Faster-Whisper (Tiny model, offline transcription)
- CustomTkinter (GUI)
- SoundDevice, MSS, Pillow, Keyboard
- Windows API (via `pywin32` and `ctypes`)

---

## ⚙️ Getting Started

### 1. Install dependencies

- pip install -r requirements.txt

### 2. Create `.env` file

- OPENAI_API_KEY=your_openai_api_key

### 3. Run the app

- python IvXAI.py

---

## 📁 File Structure

- IvXAI.py
- .env
- .cache.json
- .interview_log.txt

---

## 👤 Author
- Made with love (and late nights) by a Malaysian CS student.
- Feel free to fork, star, or improve!

---
