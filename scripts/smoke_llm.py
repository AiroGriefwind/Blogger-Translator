from config.settings import Settings
from translator.siliconflow_client import SiliconFlowClient


def main() -> None:
    settings = Settings.load(require_storage=False)
    client = SiliconFlowClient(
        api_key=settings.siliconflow_api_key,
        base_url=settings.siliconflow_base_url,
        model=settings.siliconflow_model,
        timeout=settings.siliconflow_timeout_seconds,
        max_retries=settings.siliconflow_max_retries,
    )
    text = client.chat(
        system_prompt="You are a concise translator.",
        user_prompt="Translate to English: 巴士的报是一家香港媒体。",
        temperature=settings.siliconflow_temperature,
    )
    print(text)


if __name__ == "__main__":
    main()

