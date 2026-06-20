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

    settings = get_settings()
    selected_job_ids = resolve_job_ids(job_ids or settings.scheduler_job_ids)

    scheduler.remove_all_jobs()

    action = "Reconfiguring" if scheduler.running else "Starting"
    print(f"{action} QuantPulse Scheduler:", ", ".join(selected_job_ids))

    _add_jobs(scheduler, selected_job_ids)

    if scheduler.running:
        return True

    scheduler.start()
    return True


def _add_jobs(active_scheduler, selected_job_ids):
    for job_id in selected_job_ids:
        definition = get_job_definition(job_id)

        if definition is None:
            print(f"Skipping unknown scheduler job: {job_id}")
            continue

        job_function = definition.load()
        active_scheduler.add_job(job_function, **definition.schedule_kwargs())
