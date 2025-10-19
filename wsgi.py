import os
from pathlib import Path
from dotenv import load_dotenv
from qventory import create_app

# Load environment variables from .env file
# Try .env.local first (for local development), then fall back to .env
base_path = Path(__file__).parent
dotenv_local = base_path / '.env.local'
dotenv_default = base_path / '.env'

if dotenv_local.exists():
    load_dotenv(dotenv_local)
    print(f"Loaded environment from: {dotenv_local}")
elif dotenv_default.exists():
    load_dotenv(dotenv_default)
    print(f"Loaded environment from: {dotenv_default}")
else:
    print("Warning: No .env or .env.local file found. Using system environment variables.")

app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
