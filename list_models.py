import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv(override=True)

try:
    genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
    print("Available Models for Generation:")
    found = False
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(f"- {m.name}")
            found = True
            
    if not found:
        print("No models found with generateContent capability.")
except Exception as e:
    print(f"Error fetching models: {e}")
