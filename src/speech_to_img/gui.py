import sys, os, time, threading
import json, time, requests, base64, pyaudio, wave
from datetime import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QFrame, QMessageBox
)
from PySide6.QtGui import QPixmap, QMovie
from PySide6.QtCore import Qt, QSize, QThread, Signal, QEasingCurve, QPropertyAnimation
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QApplication
from PIL import Image
from io import BytesIO
import speech_recognition as sr 

# import your existing classes here
from main import VoiceToImg, AudioToText  

class VoiceToImg:
    def __init__(self, url, api_key, secret_key) -> None:
        self.URL = url
        self.AUTH_HEADERS = {
            'X-Key': f'Key {api_key}',
            'X-Secret': f'Secret {secret_key}',
        }

    def get_pipeline(self):
        response = requests.get(self.URL + 'key/api/v1/pipelines', headers=self.AUTH_HEADERS)
        data = response.json()
        return data[0]['id']

    def generate(self, prompt, pipeline_id, images=1, width=1024, height=1024) -> list:
        params = {
            "type": "GENERATE",
            "numImages": images,
            "width": width,
            "height": height,
            "generateParams": {
                "query": f"{prompt}"
            }
        }

        data = {
            'pipeline_id': (None, pipeline_id),
            'params': (None, json.dumps(params), 'application/json')
        }
        response = requests.post(self.URL + 'key/api/v1/pipeline/run', headers=self.AUTH_HEADERS, files=data)
        data = response.json()
        return data['uuid']

    def check_generation(self, request_id, attempts=10, delay=10) -> None:
        while attempts > 0:
            response = requests.get(self.URL + 'key/api/v1/pipeline/status/' + request_id, headers=self.AUTH_HEADERS)
            data = response.json()
            if data['status'] == 'DONE':
                return data['result']['files']

            attempts -= 1
            time.sleep(delay)

    def convert(self, file, watermark_path="../../resources/big.png") -> None:
        # Decode base64 and create main image
        image_data = base64.b64decode(file)
        image = Image.open(BytesIO(image_data)).convert("RGBA")

        # Open watermark
        watermark = Image.open(watermark_path).convert("RGBA")

        # --- Extend canvas ---
        padding = image.height // 6  # height of white rectangle (e.g., 1/6 of image)
        new_height = image.height + padding
        extended = Image.new("RGBA", (image.width, new_height), "WHITE")

        # Paste original image at the top
        extended.paste(image, (0, 0))

        # Resize watermark to fit inside white rectangle
        max_wm_width = image.width // 2
        wm_height = int(watermark.height * (max_wm_width / watermark.width))
        watermark = watermark.resize((max_wm_width, wm_height), Image.LANCZOS)

        # Position watermark at the center of the white rectangle
        x = (image.width - watermark.width) // 2
        y = image.height + (padding - watermark.height) // 2

        # Paste watermark with transparency
        extended.paste(watermark, (x, y), mask=watermark)

        # Convert to RGB for saving (removes alpha channel)
        final_image = extended.convert("RGB")

        # Save result
        final_image.save("../../data/output_image.png", "PNG")

class AudioToText:
    def __init__(self, sample_rate=16000, channels=1):
        self.sample_rate = sample_rate
        self.channels = channels
        self.format = pyaudio.paInt16
        self.chunk = 1024

    def record_audio(self, filename, duration=10):
        """Record audio from microphone"""
        p = pyaudio.PyAudio()
        stream = p.open(format=self.format,
                        channels=self.channels,
                        rate=self.sample_rate,
                        input=True,
                        frames_per_buffer=self.chunk)
        print(f"Recording for {duration} seconds...")
        frames = []
        for _ in range(0, int(self.sample_rate / self.chunk * duration)):
            data = stream.read(self.chunk)
            frames.append(data)
        print("Recording finished!")
        stream.stop_stream()
        stream.close()
        p.terminate()
        with wave.open(filename, 'wb') as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(p.get_sample_size(self.format))
            wf.setframerate(self.sample_rate)
            wf.writeframes(b''.join(frames))

    def audio_to_text(self, audio_filename):
        """Convert audio file to text"""
        recognizer = sr.Recognizer()
        with sr.AudioFile(audio_filename) as source:
            recognizer.adjust_for_ambient_noise(source)
            audio_data = recognizer.record(source)
        try:
            text = recognizer.recognize_google(audio_data, language='ru-RU')
            return text
        except sr.UnknownValueError:
            print("Google Speech Recognition could not understand audio")
            return ""
        except sr.RequestError as e:
            print(f"Could not request results from Google Speech Recognition service; {e}")
            return ""

class Worker(QThread):
    countdown_signal = Signal(str)
    prompt_signal = Signal(str)
    image_signal = Signal(str)
    error_signal = Signal(str)

    def run(self):
        try:
            # Prepare audio file path
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            audio_file = f"../../data/recording_{timestamp}.wav"
            audio = AudioToText()

            # Start audio recording in a separate thread
            record_thread = threading.Thread(
                target=audio.record_audio, args=(audio_file, 10)
            )
            record_thread.start()

            # Countdown in parallel
            for i in range(10, 0, -1):
                self.countdown_signal.emit(f"Запись... {i}s")
                time.sleep(1)
            self.countdown_signal.emit("Запись окончена!")

            # Wait for recording to finish (if not already)
            record_thread.join()

            # Speech-to-text
            prompt = audio.audio_to_text(audio_file)
            # self.prompt_signal.emit(f"Prompt: {prompt}")

            # Image generation
            api = VoiceToImg('https://api-key.fusionbrain.ai/', '49CC90971A6C200C1BF6176BDDD99B39', 'F0D46F71B7788FF907A7DB87B9630365')
            pipeline_id = api.get_pipeline()
            uuid = api.generate(prompt, pipeline_id)
            files = api.check_generation(uuid)

            if files and isinstance(files, list) and len(files) > 0:
                base64_str = files[0]
                output_path = f"output_{timestamp}.png"
                api.convert(base64_str)  # saves to ../../data/output_image.png
                self.image_signal.emit("../../data/output_image.png")
            else:
                self.error_signal.emit("❌ Image generation failed.")

        except Exception as e:
            self.error_signal.emit(str(e))

class VoiceToImageApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("🎙️ Voice → Image Generator")
        self.setGeometry(400, 200, 650, 750)

        # Background
        self.setStyleSheet("""
            QWidget {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 #2e026d, stop:0.5 #6a11cb, stop:1 #ff0099
                );
                font-family: 'Segoe UI', Arial, sans-serif;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(25)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

        # Title
        title = QLabel("ГОЛОС → ИЗОБРАЖЕНИЕ")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("""
            QLabel {
            font-size: 30px;
            font-weight: 800;
            color: white;
            letter-spacing: 2px;
            background: rgba(255,255,255,0.08);
            border-radius: 18px;
            border: 1px solid rgba(255,255,255,0.3);
            padding: 18px;
            }
        """)
        layout.addWidget(title)

        # Image frame
        self.image_frame = QFrame()
        self.image_frame.setStyleSheet("""
            QFrame {
                background: rgba(255,255,255,0.05);
                border-radius: 20px;
                padding: 12px;
            }
        """)
        image_layout = QVBoxLayout()
        self.image_label = QLabel("Изображение появится здесь")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet("""
            QLabel {
                color: #ddd;
                font-size: 16px;
            }
        """)
        image_layout.addWidget(self.image_label)
        self.image_frame.setLayout(image_layout)
        layout.addWidget(self.image_frame)
        
        # Start button
        self.start_button = QPushButton("🎤 НАЧАТЬ ЗАПИСЬ")
        self.start_button.setFixedSize(280, 65)
        self.start_button.setStyleSheet("""
            QPushButton {
                background-color: #ff0099;
                color: white;
                font-size: 20px;
                font-weight: bold;
                border-radius: 30px;
                padding: 12px;
            }
            QPushButton:hover { background-color: #ff33aa; }
            QPushButton:pressed { background-color: #cc0077; }
            QPushButton:disabled { background-color: #663366; color: #aaa; }
        """)
        self.start_button.clicked.connect(self.start_process)
        layout.addWidget(self.start_button, alignment=Qt.AlignmentFlag.AlignCenter)

        # Countdown label (with glow effect)
        self.countdown_label = QLabel("Нажмите запись")
        self.countdown_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Set transparent background and remove borders
        self.countdown_label.setStyleSheet("""
            QLabel {
                background: transparent;
                border: none;
                font-size: 24px;
                font-weight: bold;
                color: white;  /* Or whatever text color you prefer */
            }
        """)

        # Ensure the widget itself has transparent attributes
        self.countdown_label.setAttribute(Qt.WA_TranslucentBackground)

        self.glow = QGraphicsDropShadowEffect()
        self.glow.setColor(Qt.magenta)
        self.glow.setOffset(0, 0)
        self.glow.setBlurRadius(20)  # You can adjust this for glow intensity
        self.countdown_label.setGraphicsEffect(self.glow)
        layout.addWidget(self.countdown_label)

        # Spinner
        self.spinner_label = QLabel()
        self.spinner_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Set transparent background
        self.spinner_label.setStyleSheet("""
            QLabel {
                background: transparent;
                border: none;
            }
        """)

        # Ensure transparent background attribute
        self.spinner_label.setAttribute(Qt.WA_TranslucentBackground)
        self.spinner_label.setAutoFillBackground(False)

        # Load spinner GIF
        spinner_path = os.path.join(os.path.dirname(__file__), "../../resources/Spin@1x-0.6s-200px-200px.gif")
        spinner_gif = QMovie(spinner_path)
        self.spinner_label.setMovie(spinner_gif)
        self.spinner_label.setVisible(False)
        self.spinner_gif = spinner_gif

        # Add spinner to the image frame layout instead of main layout
        # Assuming your image frame is called image_frame or similar
        self.image_frame.layout().addWidget(self.spinner_label)  # Add to image frame layout

        self.setLayout(layout)

    # 🔥 Restore start_process (from your original code)
    def start_process(self):
        self.start_button.setEnabled(False)
        # self.prompt_label.setText("")
        self.spinner_label.setVisible(True)
        self.spinner_gif.start()

        self.worker = Worker()
        self.worker.countdown_signal.connect(self.update_countdown)
        self.worker.prompt_signal.connect(self.update_prompt)
        self.worker.image_signal.connect(self.show_image)
        self.worker.error_signal.connect(self.show_error)
        self.worker.finished.connect(self.reset_ui)
        self.worker.start()

    def update_countdown(self, text):
        self.countdown_label.setText(text)

    def update_prompt(self, text):
        self.prompt_label.setText(text)

    def show_image(self, path):
        if os.path.exists(path):
            pixmap = QPixmap(path).scaled(
                450, 450,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.image_label.setPixmap(pixmap)

    def show_error(self, msg):
        QMessageBox.critical(self, "Error", msg)

    def reset_ui(self):
        self.start_button.setEnabled(True)
        self.spinner_label.setVisible(False)
        self.spinner_gif.stop()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = VoiceToImageApp()
    window.show()
    sys.exit(app.exec())