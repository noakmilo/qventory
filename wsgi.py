import os
from pathlib import Path
from dotenv import load_dotenv
from qventory import create_app

# Load environment variables from .env file
dotenv_path = Path(__file__).parent / '.env'
if dotenv_path.exists():
    load_dotenv(dotenv_path)

app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
