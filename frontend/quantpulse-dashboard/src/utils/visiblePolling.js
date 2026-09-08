// One in-flight read cycle; abort hidden/unmounted work and resume on visibility.
// run returns the next delay, or null to stop retries (e.g. authentication errors).
export function startVisiblePolling(run, { interval = 60000, page = document, timers = window } = {}) {
  let stopped = false, inFlight = false, controller, timer;
  async function poll() {
    if (stopped || inFlight || page.visibilityState === "hidden") return;
    inFlight = true;
    controller = new AbortController();
    let delay = interval;
    try { delay = await run(controller.signal); }
    finally {
      inFlight = false;
      if (!stopped && page.visibilityState !== "hidden") {
        if (controller.signal.aborted) delay = 0;
        if (delay != null) timer = timers.setTimeout(poll, delay);
      }
    }
  }
  function visibilityChanged() {
    timers.clearTimeout(timer);
    if (page.visibilityState === "hidden") controller?.abort();
    else void poll();
  }
  page.addEventListener("visibilitychange", visibilityChanged);
  void poll();
  return () => {
    stopped = true;
    timers.clearTimeout(timer);
    controller?.abort();
    page.removeEventListener("visibilitychange", visibilityChanged);
  };
}
