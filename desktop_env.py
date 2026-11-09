"""Settings for the desktop app: the .env template and the user's settings file.

The template (.env.example, bundled into the app) provides the Azure endpoint and
deployment names; the user's .env in the app-data folder (CLOSECALL_ENV_FILE)
adds their key, written by the setup page on first start.

Only AZURE_* settings are taken from the template: USERNAME/PASSWORD belong to
the browser login, and USERNAME would shadow the Windows variable of that name.
"""

import os
import tempfile

from dotenv import dotenv_values

TEMPLATE = ".env.example"


def template_settings() -> dict[str, str]:
    """Non-empty AZURE_* values from the template."""
    values = dotenv_values(TEMPLATE) if os.path.exists(TEMPLATE) else {}
    return {k: v for k, v in values.items() if k.startswith("AZURE_") and v}


def load() -> None:
    """Apply the template, then the user's .env on top of it."""
    os.environ.update(template_settings())
    user_env = os.environ.get("CLOSECALL_ENV_FILE", "")
    if user_env and os.path.exists(user_env):
        os.environ.update({k: v for k, v in dotenv_values(user_env).items() if v})


def save_api_key(api_key: str) -> None:
    """Write the user's .env from the template plus their key, and apply it."""
    path = os.environ["CLOSECALL_ENV_FILE"]
    settings = {**template_settings(), "AZURE_OPENAI_API_KEY": api_key}
    content = "# Close Call settings, written by the setup page\n" + "".join(
        f"{k}={v}\n" for k, v in settings.items()
    )

    # Write atomically and readable only by this user
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".env.")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)

    os.environ.update(settings)
