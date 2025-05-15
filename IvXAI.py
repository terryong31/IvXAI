import mss
import base64
import openai
import time
from PIL import Image
import io
import os
import json
from datetime import datetime
from dotenv import load_dotenv
import customtkinter as ctk
import keyboard
import threading
import sys
import ctypes
import platform
import win32gui
import win32con
import sounddevice as sd
import soundfile as sf
import numpy as np
from faster_whisper import WhisperModel

# Load environment variables from .env file
load_dotenv()

# Initialize OpenAI client with API key from .env
client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Global variables for GUI window
root = None
text_widget = None
window_x, window_y = 1510, 0  # Initial window position
is_processing = False  # Prevent multiple simultaneous captures
last_key_time = 0  # For debouncing hotkeys
app_destroyed = False  # Track if app has been terminated
is_hidden = False  # Track if the overlay is hidden
is_recording_audio = False  # Track audio recording state
audio_data = []  # Store audio frames
sample_rate = 16000  # Reduced sample rate for faster processing
audio_stream = None  # Track the active stream
response_cache = {}  # In-memory cache for question-response pairs
whisper_model = None  # Local Whisper model

# Cache and log file paths (discreet names)
CACHE_FILE = ".cache.json"
LOG_FILE = ".interview_log.txt"

# Initialize Whisper model at startup
def init_whisper():
    global whisper_model
    try:
        whisper_model = WhisperModel("tiny", device="cpu", compute_type="int8")
        print("Initialized local Whisper model (tiny)")
    except Exception as e:
        print(f"Error initializing Whisper model: {str(e)}")

# Load cache from disk
def load_cache():
    global response_cache
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, "r") as f:
                response_cache = json.load(f)
            print(f"Loaded cache from {CACHE_FILE}")
    except Exception as e:
        print(f"Error loading cache: {str(e)}")

# Save cache to disk
def save_cache():
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(response_cache, f)
        print(f"Saved cache to {CACHE_FILE}")
    except Exception as e:
        print(f"Error saving cache: {str(e)}")

# Log interaction to file
def log_interaction(interaction_type, input_text, response):
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = (
            f"[{timestamp}] {interaction_type}\n"
            f"Input: {input_text}\n"
            f"Response: {response}\n"
            f"{'-'*50}\n"
        )
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_entry)
        print(f"Logged {interaction_type} to {LOG_FILE}")
    except Exception as e:
        print(f"Error logging interaction: {str(e)}")

# Define ctypes bindings for SetWindowDisplayAffinity
user32 = ctypes.WinDLL('user32', use_last_error=True)
SetWindowDisplayAffinity = user32.SetWindowDisplayAffinity
SetWindowDisplayAffinity.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.DWORD]
SetWindowDisplayAffinity.restype = ctypes.wintypes.BOOL

# Define bindings for SetWindowLong and GetWindowLong
SetWindowLong = user32.SetWindowLongW
SetWindowLong.argtypes = [ctypes.wintypes.HWND, ctypes.c_int, ctypes.wintypes.LONG]
SetWindowLong.restype = ctypes.wintypes.LONG
GetWindowLong = user32.GetWindowLongW
GetWindowLong.argtypes = [ctypes.wintypes.HWND, ctypes.c_int]
GetWindowLong.restype = ctypes.wintypes.LONG

# Define WDA_EXCLUDEFROMCAPTURE constant
WDA_EXCLUDEFROMCAPTURE = 0x00000011

def boolcheck(result, func, args):
    """Error checking for ctypes calls."""
    if not result:
        raise ctypes.WinError(ctypes.get_last_error())
    return result

SetWindowDisplayAffinity.errcheck = boolcheck

def audio_callback(indata, frames, time, status):
    """Callback for recording audio."""
    if status:
        print(f"Audio callback status: {status}")
    if is_recording_audio:
        audio_data.append(indata.copy())

def capture_screen():
    """Capture the screen using mss, resize it, and return the image as a base64-encoded string."""
    with mss.mss() as sct:
        monitor = sct.monitors[1]
        screenshot = sct.grab(monitor)
        img = Image.frombytes("RGB", (screenshot.width, screenshot.height), screenshot.rgb)
        new_size = (int(img.width * 0.5), int(img.height * 0.5))
        img = img.resize(new_size, Image.Resampling.LANCZOS)
        buffered = io.BytesIO()
        img.save(buffered, format="PNG", optimize=True)
        return base64.b64encode(buffered.getvalue()).decode('utf-8')

def describe_image(base64_image):
    """Use OpenAI API to describe the image and generate a solution if it contains a coding question."""
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Describe what is on the screen in this image in Malaysian English. If the screen contains a coding question "
                                "(e.g., from websites like LeetCode, Codewars, or similar), also provide a solution in Python, lah. "
                                "Format the response with the description first, followed by the solution (if applicable) in a code block, can?"
                            )
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{base64_image}"
                            }
                        }
                    ]
                }
            ],
            max_tokens=1000
        )
        response_text = response.choices[0].message.content
        # Log interaction
        log_interaction("Image Capture", "Screen content", response_text)
        return response_text
    except Exception as e:
        error_msg = f"Error describing image: {str(e)}"
        log_interaction("Image Capture", "Screen content", error_msg)
        return error_msg

def transcribe_audio(audio_data, sample_rate):
    """Transcribe audio data using local faster-whisper model."""
    global whisper_model
    if whisper_model is None:
        return "Error: Whisper model not initialized"
    try:
        # Save audio to in-memory buffer
        buffer = io.BytesIO()
        sf.write(buffer, audio_data, sample_rate, format='WAV')
        buffer.seek(0)
        # Transcribe using faster-whisper
        segments, info = whisper_model.transcribe(buffer, language=None)  # Auto-detect language
        transcription = " ".join(segment.text for segment in segments)
        buffer.close()
        return transcription.strip()
    except Exception as e:
        return f"Error transcribing audio: {str(e)}"

def generate_response_from_text(text):
    """Generate a conversational response from transcribed text using OpenAI API with caching."""
    # Normalize text for cache key (lowercase, strip)
    cache_key = text.lower().strip()
    
    # Check cache
    if cache_key in response_cache:
        print(f"Cache hit for question: {text}")
        response = response_cache[cache_key]
        log_interaction("Audio Transcription", text, response)
        return response
    
    try:
        # Detect if input is likely Malay (basic heuristic)
        is_malay = any(word.lower() in ['adalah', 'saya', 'anda', 'bagaimana', 'apa'] for word in text.split())
        language = 'Malay' if is_malay else 'English'
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"You are a friendly assistant answering in {language} with a Malaysian conversational tone, lah. "
                        "Use phrases like 'can lah', 'no problem', or 'sure thing' to sound human-like. "
                        "Assume the input is a real-time interview question (technical, behavioral, or general). "
                        "Provide a concise answer in bullet points, like how you'd respond in an interview, max 3 points. "
                        "If the question is about coding, include a Python solution in a code block, but only if explicitly asked or clearly a programming question. "
                        "Keep it short, under 100 words, no essay, okay?"
                    )
                },
                {
                    "role": "user",
                    "content": f"Question: {text}"
                }
            ],
            max_tokens=300
        )
        response_text = response.choices[0].message.content
        # Update cache
        response_cache[cache_key] = response_text
        save_cache()
        # Log interaction
        log_interaction("Audio Transcription", text, response_text)
        return response_text
    except Exception as e:
        error_msg = f"Error generating response: {str(e)}"
        log_interaction("Audio Transcription", text, error_msg)
        return error_msg

def toggle_audio_recording():
    """Toggle system audio recording and process when stopped."""
    global is_recording_audio, audio_data, audio_stream
    if is_hidden or app_destroyed:
        return
    if not is_recording_audio:
        # Start recording
        audio_data = []
        is_recording_audio = True
        print("Ctrl+Alt+R pressed, starting audio recording")
        root.after(0, update_gui, "Recording audio...")
        try:
            # Start audio stream
            audio_stream = sd.InputStream(samplerate=sample_rate, channels=2, callback=audio_callback)
            audio_stream.start()
            print("Audio stream started")
            # Auto-stop after 15 seconds
            threading.Timer(15.0, lambda: toggle_audio_recording() if is_recording_audio else None).start()
        except Exception as e:
            is_recording_audio = False
            audio_stream = None
            root.after(0, update_gui, f"Error starting audio recording: {str(e)}")
            print(f"Error starting audio: {str(e)}")
            return
    else:
        # Stop recording
        is_recording_audio = False
        print("Ctrl+Alt+R pressed, stopping audio recording")
        try:
            # Stop and close stream
            if audio_stream:
                audio_stream.stop()
                audio_stream.close()
                audio_stream = None
                print("Audio stream stopped")
            # Process audio
            root.after(0, update_gui, "Processing audio...")
            if not audio_data:
                root.after(0, update_gui, "No audio recorded")
                print("No audio data captured")
                return
            # Process audio in-memory
            audio_array = np.concatenate(audio_data, axis=0)
            # Transcribe audio
            transcription = transcribe_audio(audio_array, sample_rate)
            if transcription.startswith("Error"):
                root.after(0, update_gui, transcription)
                print(f"Transcription error: {transcription}")
                return
            # Generate response
            response = generate_response_from_text(transcription)
            # Display transcription and response
            display_text = f"Transcription:\n{transcription}\n\nResponse:\n{response}"
            root.after(0, update_gui, display_text)
            print("Audio processed and displayed")
        except Exception as e:
            root.after(0, update_gui, f"Error processing audio: {str(e)}")
            print(f"Error processing audio: {str(e)}")
            audio_stream = None

def update_gui(text):
    """Update the GUI text widget with the given text."""
    if text_widget and not app_destroyed:
        print(f"Updating GUI with text: {text[:50]}...")
        text_widget.configure(state="normal")
        text_widget.delete("1.0", ctk.END)
        text_widget.insert("1.0", text)
        text_widget.configure(state="disabled")
        text_widget.update()
        root.update()
        print("GUI updated")

def handle_capture():
    """Capture screen and update GUI when Ctrl+Alt+Z is pressed."""
    global is_processing
    if is_processing or app_destroyed or is_hidden:
        return
    is_processing = True
    try:
        print("Ctrl+Alt+Z pressed, capturing screen")
        root.after(0, update_gui, "Loading...")
        base64_image = capture_screen()
        description = describe_image(base64_image)
        root.after(0, update_gui, description)
    finally:
        is_processing = False

def scroll_text_up():
    """Scroll the text widget up by 5 lines."""
    if text_widget and not app_destroyed:
        print("Ctrl+Alt+U pressed, scrolling up 5 lines")
        text_widget.yview_scroll(-5, "units")

def scroll_text_down():
    """Scroll the text widget down by 5 lines."""
    if text_widget and not app_destroyed:
        print("Ctrl+Alt+J pressed, scrolling down 5 lines")
        text_widget.yview_scroll(5, "units")

def toggle_visibility():
    """Placeholder for toggle visibility."""
    print("Ctrl+Alt+X pressed: Toggle visibility is not required as the overlay is hidden from screen sharing by default. Use Ctrl+Alt+M to hide/show as a fallback.")

def toggle_hide():
    """Hide or show the overlay."""
    global window_x, window_y, is_hidden
    if app_destroyed:
        return
    if not is_hidden:
        window_x, window_y = root.winfo_x(), root.winfo_y()
        root.withdraw()
        is_hidden = True
        print("Overlay hidden (Ctrl+Alt+M)")
    else:
        root.deiconify()
        root.geometry(f"+{window_x}+{window_y}")
        is_hidden = False
        print("Overlay shown (Ctrl+Alt+M)")

def kill_app():
    """Immediately terminate the application when Ctrl+Alt+Q is pressed."""
    global root, app_destroyed, is_recording_audio, audio_stream
    print("Terminated by Ctrl+Alt+Q")
    # Stop audio recording if active
    if is_recording_audio:
        is_recording_audio = False
        if audio_stream:
            audio_stream.stop()
            audio_stream.close()
            audio_stream = None
            print("Audio recording stopped on exit")
    keyboard.unhook_all()
    if root and not app_destroyed:
        app_destroyed = True
        root.destroy()
    sys.exit(0)

def move_window():
    """Handle window movement with Ctrl+Alt + WASD keys."""
    global window_x, window_y, last_key_time
    while not app_destroyed:
        current_time = time.time()
        if current_time - last_key_time < 0.1:
            time.sleep(0.05)
            continue
        if keyboard.is_pressed('ctrl+alt+w'):
            window_y -= 40
            root.geometry(f"+{window_x}+{window_y}")
            last_key_time = current_time
            print("Moving overlay: Ctrl+Alt+W (Up)")
        elif keyboard.is_pressed('ctrl+alt+s'):
            window_y += 40
            root.geometry(f"+{window_x}+{window_y}")
            last_key_time = current_time
            print("Moving overlay: Ctrl+Alt+S (Down)")
        elif keyboard.is_pressed('ctrl+alt+a'):
            window_x -= 80
            root.geometry(f"+{window_x}+{window_y}")
            last_key_time = current_time
            print("Moving overlay: Ctrl+Alt+A (Left)")
        elif keyboard.is_pressed('ctrl+alt+d'):
            window_x += 80
            root.geometry(f"+{window_x}+{window_y}")
            last_key_time = current_time
            print("Moving overlay: Ctrl+Alt+D (Right)")
        time.sleep(0.05)

def setup_gui():
    """Set up the modern, semi-transparent, click-through overlay window."""
    global root, text_widget
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")

    root = ctk.CTk()
    print("GUI initialized")
    root.title("ScreenDescriptionOverlay123")
    root.geometry("400x500+1510+0")
    root.attributes('-alpha', 0.7)
    root.attributes('-topmost', True)
    root.overrideredirect(True)

    root.protocol("WM_DELETE_WINDOW", lambda: kill_app())
    root.bind("<Configure>", lambda e: root.attributes('-alpha', 0.7))

    if platform.system() == "Windows":
        try:
            root.update()
            time.sleep(0.1)
            title = root.title()
            hwnd = win32gui.FindWindow(None, title)
            print(f"Applying SetWindowDisplayAffinity to HWND: {hwnd}")
            if not user32.IsWindow(hwnd):
                raise ValueError(f"Invalid window handle: {hwnd}")
            ex_style = GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            ex_style |= win32con.WS_EX_TRANSPARENT | win32con.WS_EX_LAYERED
            SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex_style)
            print("Applied click-through styles (WS_EX_TRANSPARENT, WS_EX_LAYERED)")
            SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
            print("Applied SetWindowDisplayAffinity with WDA_EXCLUDEFROMCAPTURE to hide from screen recording (Windows)")
            print("The overlay should be visible to you but hidden from screen sharing. If screen sharing still detects the overlay, use Ctrl+Alt+M to hide as a fallback.")
        except (OSError, ValueError) as e:
            error_message = str(e)
            if isinstance(e, OSError):
                error_code = ctypes.get_last_error()
                error_message = f"{ctypes.WinError(error_code).strerror} (Error code: {error_code})"
            print(f"Failed to apply SetWindowDisplayAffinity or click-through styles: {error_message}")
            print("Falling back to hide (Ctrl+Alt+M) for screen sharing hiding.")
    else:
        print("Screen recording hiding (SetWindowDisplayAffinity) and click-through are Windows-only. Use Ctrl+Alt+M to hide for screen sharing hiding.")

    frame = ctk.CTkFrame(root, corner_radius=0, fg_color="#2B2B2B")
    frame.pack(fill="both", expand=True)

    text_widget = ctk.CTkTextbox(
        frame,
        wrap="word",
        font=("Arial", 14),
        text_color="#FFFFFF",
        corner_radius=0,
        fg_color="#2B2B2B",
        border_width=0,
        height=500,
        activate_scrollbars=True
    )
    text_widget.pack(fill="both", expand=True)
    text_widget.insert("1.0", "Ctrl+Alt+Z to capture screen\n\nCtrl+Alt+R to record audio\n\nCtrl+Alt+Q to exit\n\nCtrl+Alt+X for toggle visibility (not needed)\n\nCtrl+Alt+M to hide/show\n\nCtrl+Alt+U/J to scroll\n\nCtrl+Alt+WASD to move")
    text_widget.configure(state="disabled")
    print("Text widget initialized")

    threading.Thread(target=move_window, daemon=True).start()

    return root

def main():
    global root, app_destroyed
    # Initialize Whisper and cache
    init_whisper()
    load_cache()
    print("Starting screen description overlay... Press Ctrl+Alt+Z to capture screen, Ctrl+Alt+R to record audio, Ctrl+Alt+Q to exit, Ctrl+Alt+X for toggle visibility (not needed), Ctrl+Alt+M to hide/show, Ctrl+Alt+U/J to scroll, Ctrl+Alt+WASD to move.")

    root = setup_gui()

    try:
        keyboard.add_hotkey('ctrl+alt+z', handle_capture)
        print("Registered hotkey: Ctrl+Alt+Z")
        keyboard.add_hotkey('ctrl+alt+r', toggle_audio_recording)
        print("Registered hotkey: Ctrl+Alt+R")
        keyboard.add_hotkey('ctrl+alt+q', kill_app)
        print("Registered hotkey: Ctrl+Alt+Q")
        keyboard.add_hotkey('ctrl+alt+u', scroll_text_up)
        print("Registered hotkey: Ctrl+Alt+U")
        keyboard.add_hotkey('ctrl+alt+j', scroll_text_down)
        print("Registered hotkey: Ctrl+Alt+J")
        keyboard.add_hotkey('ctrl+alt+x', toggle_visibility)
        print("Registered hotkey: Ctrl+Alt+X")
        keyboard.add_hotkey('ctrl+alt+m', toggle_hide)
        print("Registered hotkey: Ctrl+Alt+M")
    except ValueError as e:
        print(f"Error registering hotkeys: {str(e)}")

    try:
        root.mainloop()
    except KeyboardInterrupt:
        print("Stopped by user.")
    finally:
        keyboard.unhook_all()
        if root and not app_destroyed:
            app_destroyed = True
            root.destroy()

if __name__ == "__main__":
    main()
