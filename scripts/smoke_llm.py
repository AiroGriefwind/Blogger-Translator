from config.settings import Settings
from translator.siliconflow_client import SiliconFlowClient


def main() -> None:
    settings = Settings.load()
    client = SiliconFlowClient(
        api_key=settings.siliconflow_api_key,
        base_url=settings.siliconflow_base_url,
        model=settings.siliconflow_model,
    )
    text = client.chat(
        system_prompt="You are a concise translator.",
        user_prompt="Translate to English: 巴士的报是一家香港媒体。",
    )
    print(text)


if __name__ == "__main__":
    main()

