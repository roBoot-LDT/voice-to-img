import json, time, requests, base64, pyaudio, wave
from PIL import Image
from io import BytesIO
import speech_recognition as sr 
from datetime import datetime

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

def run():
    # Generate filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    audio_file = f"../../data/recording_{timestamp}.wav"
    # Create an instance of AudioToText
    audio_to_text_instance = AudioToText()
    # Record audio (5 seconds)
    audio_to_text_instance.record_audio(audio_file, duration=10)
    # Convert to text
    prompt = audio_to_text_instance.audio_to_text(audio_file)
    print(prompt)
    api = VoiceToImg('https://api-key.fusionbrain.ai/', '49CC90971A6C200C1BF6176BDDD99B39', 'F0D46F71B7788FF907A7DB87B9630365')
    pipeline_id = api.get_pipeline()
    print("Generating...")
    uuid = api.generate(prompt, pipeline_id)
    files = api.check_generation(uuid)
    if files and isinstance(files, list) and len(files) > 0:
        base64_str = files[0]
        api.convert(base64_str)
    else:
        print("No files returned or generation failed.")
    print("Done!")

if __name__ == '__main__':
    run()
