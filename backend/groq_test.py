"""
Groq API Connectivity & Diagnostics Test.
Validates Groq client initialization, model accessibility, and basic inference.
Secrets are never printed or logged.
Windows cp1252 console encoding safe.
"""

import os
import sys
from dotenv import load_dotenv

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Search for .env in current and parent directories
load_dotenv()
backend_env = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(backend_env):
    load_dotenv(backend_env)

api_key = os.getenv("GROQ_API_KEY")
model_name = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")

if not api_key:
    print("[ERROR] GROQ_API_KEY environment variable is not set.")
    print("Please check your .env file or export GROQ_API_KEY.")
    sys.exit(1)

masked_key = api_key[:4] + "..." + api_key[-4:] if len(api_key) > 8 else "***"
print(f"[CONFIG] GROQ_API_KEY detected: {masked_key}")
print(f"[CONFIG] Target Model: {model_name}")

try:
    import groq
except ImportError:
    print("[ERROR] 'groq' package is not installed. Run: pip install groq")
    sys.exit(1)

try:
    client = groq.Groq(api_key=api_key, timeout=30.0)
    print("[STATUS] Connecting to Groq API...")
    
    # Check model list
    models = client.models.list()
    active_models = [m.id for m in models.data if getattr(m, "active", True)]
    print(f"[OK] Connected successfully! Total accessible models: {len(active_models)}")
    
    # Test inference
    print(f"[STATUS] Testing chat completion using '{model_name}'...")
    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": "You are a helpful coding diagnostic assistant."},
            {"role": "user", "content": "Reply with 'GROQ_ONLINE' and a 5-word confirmation."}
        ],
        max_tokens=60,
        temperature=0.2
    )
    
    msg = response.choices[0].message
    reply = msg.content or (getattr(msg, "reasoning", "") or "No text returned")
    print(f"[RESULT] Model Response: {reply.strip()}")
    print("[SUCCESS] Groq integration test passed successfully!")

except groq.APIConnectionError as conn_err:
    print(f"[ERROR] Connection error: {conn_err}")
    sys.exit(1)
except groq.RateLimitError as rate_err:
    print(f"[WARNING] Rate limit encountered: {rate_err}")
    sys.exit(1)
except groq.APIStatusError as status_err:
    print(f"[ERROR] Groq API error ({status_err.status_code}): {status_err.message}")
    sys.exit(1)
except Exception as exc:
    print(f"[ERROR] Unexpected diagnostic error: {exc}")
    sys.exit(1)
