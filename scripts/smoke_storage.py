from config.settings import Settings
from storage.firebase_storage_client import FirebaseStorageClient


def main() -> None:
    settings = Settings.load()
    client = FirebaseStorageClient(bucket_name=settings.firebase_storage_bucket)
    path = client.upload_json("smoke/test.json", {"ok": True})
    print(path)


if __name__ == "__main__":
    main()

