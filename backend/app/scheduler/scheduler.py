from app.config import get_settings
from app.scheduler.registry import get_job_definition
from app.scheduler.registry import resolve_job_ids


scheduler = None


def get_scheduler():
    return scheduler


def start_scheduler(job_ids=None):
    global scheduler

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except ModuleNotFoundError as exc:
        print(f"Scheduler disabled: missing dependency {exc.name}")
        return False

    if scheduler is None:
        scheduler = BackgroundScheduler(timezone="Asia/Kolkata", daemon=True)

    if scheduler.running:
        print("Scheduler already running")
        return True

    settings = get_settings()
    selected_job_ids = resolve_job_ids(job_ids or settings.scheduler_job_ids)

    scheduler.remove_all_jobs()

    print("Starting QuantPulse Scheduler:", ", ".join(selected_job_ids))

    for job_id in selected_job_ids:
        definition = get_job_definition(job_id)

        if definition is None:
            print(f"Skipping unknown scheduler job: {job_id}")
            continue

        job_function = definition.load()
        scheduler.add_job(job_function, **definition.schedule_kwargs())

    scheduler.start()
    return True
