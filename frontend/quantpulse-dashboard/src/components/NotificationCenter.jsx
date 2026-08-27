import { useCallback, useEffect, useState } from "react";
import clsx from "clsx";
import {
  Bell,
  CheckCheck,
  CircleAlert,
  CircleCheck,
  Info,
  ShieldAlert,
  X,
} from "lucide-react";
import { Link } from "react-router-dom";
import {
  loadNotifications,
  markAllNotificationsRead,
  markNotificationRead,
} from "../hooks/dashboardApi";
import { formatTimeInIst } from "../utils/formatters";


const POLL_INTERVAL_MS = 20000;


export default function NotificationCenter({ getPageHref, view }) {
  const [open, setOpen] = useState(false);
  const [records, setRecords] = useState([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const refresh = useCallback(async (signal) => {
    try {
      const payload = await loadNotifications({ limit: 50, signal });
      setRecords(Array.isArray(payload?.records) ? payload.records : []);
      setUnreadCount(Number(payload?.unreadCount || 0));
      setError("");
    } catch (requestError) {
      if (requestError?.name !== "AbortError") {
        setError("Notifications are temporarily unavailable.");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let activeController = new AbortController();
    refresh(activeController.signal);
    const intervalId = window.setInterval(() => {
      activeController.abort();
      activeController = new AbortController();
      refresh(activeController.signal);
    }, POLL_INTERVAL_MS);
    return () => {
      window.clearInterval(intervalId);
      activeController.abort();
    };
  }, [refresh]);

  const markRead = useCallback(async (notification) => {
    if (!notification || notification.isRead) return;
    setRecords((current) => current.map((item) => (
      item.id === notification.id
        ? { ...item, isRead: true, readAt: new Date().toISOString() }
        : item
    )));
    setUnreadCount((current) => Math.max(0, current - 1));
    try {
      await markNotificationRead(notification.id);
    } catch {
      refresh();
    }
  }, [refresh]);

  const markAllRead = useCallback(async () => {
    if (!unreadCount) return;
    const readAt = new Date().toISOString();
    setRecords((current) => current.map((item) => ({ ...item, isRead: true, readAt })));
    setUnreadCount(0);
    try {
      await markAllNotificationsRead();
    } catch {
      refresh();
    }
  }, [refresh, unreadCount]);

  return (
    <div className="relative shrink-0">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        title="Notifications"
        aria-label={`${unreadCount} unread notifications`}
        aria-expanded={open}
        className={clsx(
          "relative grid h-8 w-8 place-items-center rounded-lg border bg-slate-900/80 transition",
          open || unreadCount
            ? "border-cyan-400/30 text-cyan-200"
            : "border-white/10 text-slate-400 hover:border-cyan-400/30 hover:text-cyan-200"
        )}
      >
        <Bell className="h-4 w-4" />
        {unreadCount ? (
          <span className="absolute -right-1.5 -top-1.5 min-w-4 rounded-full bg-rose-500 px-1 text-center text-[10px] font-bold leading-4 text-white shadow-sm">
            {unreadCount > 99 ? "99+" : unreadCount}
          </span>
        ) : null}
      </button>

      {open ? (
        <section className="fixed inset-x-3 top-14 z-[70] overflow-hidden rounded-xl border border-white/10 bg-slate-950 shadow-2xl shadow-slate-950/60 sm:absolute sm:inset-x-auto sm:right-0 sm:top-10 sm:w-[420px]">
          <div className="flex items-center justify-between gap-3 border-b border-white/10 px-4 py-3">
            <div>
              <div className="text-sm font-semibold text-white">Notifications</div>
              <div className="text-xs text-slate-500">
                {unreadCount ? `${unreadCount} unread` : "You are up to date"}
              </div>
            </div>
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={markAllRead}
                disabled={!unreadCount}
                className="inline-flex h-8 items-center gap-1.5 rounded-lg px-2 text-xs text-cyan-200 transition hover:bg-cyan-500/10 disabled:cursor-default disabled:text-slate-600"
              >
                <CheckCheck className="h-3.5 w-3.5" />
                Mark all read
              </button>
              <button
                type="button"
                onClick={() => setOpen(false)}
                aria-label="Close notifications"
                className="grid h-8 w-8 place-items-center rounded-lg text-slate-400 transition hover:bg-white/5 hover:text-white"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          </div>

          <div className="max-h-[min(72vh,620px)] overflow-y-auto qp-scrollbar">
            {loading ? (
              <div className="px-4 py-8 text-center text-sm text-slate-500">Loading notifications...</div>
            ) : error && !records.length ? (
              <div className="px-4 py-8 text-center text-sm text-amber-300">{error}</div>
            ) : !records.length ? (
              <div className="px-4 py-10 text-center">
                <Bell className="mx-auto h-6 w-6 text-slate-600" />
                <div className="mt-2 text-sm text-slate-400">No notifications yet</div>
                <div className="mt-1 text-xs text-slate-600">Official paper-trade events will appear here.</div>
              </div>
            ) : (
              <div className="divide-y divide-white/5">
                {records.map((notification) => (
                  <NotificationRow
                    key={notification.id}
                    notification={notification}
                    href={notification.symbol
                      ? getPageHref("coin-details", { ...view, symbol: notification.symbol })
                      : null}
                    onRead={() => markRead(notification)}
                    onNavigate={() => setOpen(false)}
                  />
                ))}
              </div>
            )}
          </div>

          <div className="border-t border-white/10 px-4 py-2 text-[10px] text-slate-600">
            Official portfolio only · Shadow strategy trades are intentionally silent · Times shown in IST
          </div>
        </section>
      ) : null}
    </div>
  );
}


function NotificationRow({ notification, href, onRead, onNavigate }) {
  const content = (
    <>
      <NotificationIcon severity={notification.severity} />
      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-3">
          <div className={clsx("text-sm", notification.isRead ? "font-medium text-slate-300" : "font-semibold text-white")}>
            {notification.title}
          </div>
          {!notification.isRead ? <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-cyan-400" /> : null}
        </div>
        <div className="mt-1 text-xs leading-5 text-slate-400">{notification.message}</div>
        <div className="mt-1.5 flex flex-wrap items-center gap-x-2 text-[10px] uppercase tracking-[0.1em] text-slate-600">
          <span>{notification.category}</span>
          {notification.symbol ? <span>{notification.symbol}</span> : null}
          <span>{formatTimeInIst(notification.createdAt)}</span>
        </div>
      </div>
    </>
  );
  const className = clsx(
    "flex w-full items-start gap-3 px-4 py-3 text-left transition hover:bg-white/5",
    !notification.isRead && "bg-cyan-500/[0.04]"
  );

  if (href) {
    return (
      <Link to={href} onClick={() => { onRead(); onNavigate(); }} className={className}>
        {content}
      </Link>
    );
  }
  return (
    <button type="button" onClick={onRead} className={className}>
      {content}
    </button>
  );
}


function NotificationIcon({ severity }) {
  const normalized = String(severity || "INFO").toUpperCase();
  const config = {
    SUCCESS: { Icon: CircleCheck, classes: "border-emerald-400/20 bg-emerald-500/10 text-emerald-300" },
    WARNING: { Icon: CircleAlert, classes: "border-amber-400/20 bg-amber-500/10 text-amber-300" },
    CRITICAL: { Icon: ShieldAlert, classes: "border-rose-400/20 bg-rose-500/10 text-rose-300" },
    INFO: { Icon: Info, classes: "border-cyan-400/20 bg-cyan-500/10 text-cyan-300" },
  }[normalized] || { Icon: Info, classes: "border-cyan-400/20 bg-cyan-500/10 text-cyan-300" };
  const Icon = config.Icon;
  return (
    <span className={clsx("grid h-8 w-8 shrink-0 place-items-center rounded-lg border", config.classes)}>
      <Icon className="h-4 w-4" />
    </span>
  );
}
