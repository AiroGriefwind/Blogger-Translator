from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from config.settings import Settings
from storage.firebase_storage_client import FirebaseStorageClient
from storage.repositories import RunRepository


def main() -> None:
    settings = Settings.load()
    cred_path = Path(settings.google_application_credentials)
    if not cred_path.exists():
        raise SystemExit(
            "GOOGLE_APPLICATION_CREDENTIALS 指向的文件不存在："
            f"{cred_path}\n"
            "请将 .env 中该值改为本机 service-account.json 的真实路径后重试。"
        )

    client = FirebaseStorageClient(bucket_name=settings.firebase_storage_bucket)
    repo = RunRepository(storage=client)

    now = datetime.now(tz=timezone.utc)
    date_key = now.strftime("%Y%m%d")
    run_id = f"smoke_{now.strftime('%Y%m%d%H%M%S')}"
    path = repo.save_run_log(
        date_key=date_key,
        run_id=run_id,
        payload={
            "run_id": run_id,
            "date_key": date_key,
            "started_at": now.isoformat(),
            "ended_at": now.isoformat(),
            "overall_status": "success",
            "steps": {
                "storage_connectivity": {
                    "status": "success",
                    "started_at": now.isoformat(),
                    "ended_at": now.isoformat(),
                    "duration_ms": 0,
                    "error": None,
                }
            },
            "artifacts": {},
        },
    )
    print(f"run_id={run_id}")
    print(path)


if __name__ == "__main__":
    main()

