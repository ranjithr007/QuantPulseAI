from fastapi import APIRouter, HTTPException, Query

from app.database.sqlserver import SessionLocal
from app.repositories.notification_repository import NotificationRepository
from app.repositories.notification_repository import notification_payload


router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("")
def list_notifications(
    unread_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
):
    db = SessionLocal()
    try:
        repo = NotificationRepository()
        records = repo.list(db, unread_only=unread_only, limit=limit)
        return {
            "source": "app_notifications_v1",
            "count": len(records),
            "unreadCount": repo.unread_count(db),
            "records": [notification_payload(row) for row in records],
        }
    finally:
        db.close()


@router.get("/unread-count")
def notification_unread_count():
    db = SessionLocal()
    try:
        return {
            "source": "app_notifications_v1",
            "unreadCount": NotificationRepository().unread_count(db),
        }
    finally:
        db.close()


@router.patch("/{notification_id}/read")
def mark_notification_read(notification_id: int):
    db = SessionLocal()
    try:
        row = NotificationRepository().mark_read(db, notification_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Notification not found")
        return {
            "source": "app_notifications_v1",
            "notification": notification_payload(row),
        }
    finally:
        db.close()


@router.post("/read-all")
def mark_all_notifications_read():
    db = SessionLocal()
    try:
        count, read_at = NotificationRepository().mark_all_read(db)
        return {
            "source": "app_notifications_v1",
            "updatedCount": count,
            "readAt": read_at,
            "unreadCount": 0,
        }
    finally:
        db.close()
