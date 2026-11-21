"""One test push to the phone (manual workflow 'push test'): checks the FCM secret and the topic."""
from . import push


def main():
    if not push.configured():
        raise SystemExit("push test: FCM_SERVICE_ACCOUNT is not set")
    item = {"id": 0, "model": "Тест", "price_start": 1, "url": "https://www.vinted.de/", "description": "Тестовое уведомление трекера."}
    sent = push.send_cameras([item], {}, letter="Тест")
    print(f"push test: sent {sent}")
    if not sent:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
