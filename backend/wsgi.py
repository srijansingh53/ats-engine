from pathlib import Path

from dotenv import load_dotenv

# Load backend/.env or the repo-root .env if present (real env vars take precedence)
for env in (Path(__file__).with_name(".env"), Path(__file__).resolve().parent.parent / ".env"):
    if env.is_file():
        load_dotenv(env, override=False)

from ats import create_app

app = create_app()

if __name__ == "__main__":
    import os

    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5001")), debug=True)
