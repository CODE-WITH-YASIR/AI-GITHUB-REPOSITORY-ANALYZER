import os
from dotenv import load_dotenv
from google import genai

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    raise ValueError("GEMINI_API_KEY not found")

client = genai.Client(api_key=api_key)

print("Connecting to Gemini...")

interaction = client.interactions.create(
    model="gemini-3.6-flash",
    input="Reply only: Gemini connection successful",
)

print(interaction.output_text)