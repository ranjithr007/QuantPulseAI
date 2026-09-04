export function notificationHref(notification, getPageHref, view) {
  if (notification?.category === "STRATEGY") {
    return getPageHref("strategies", view);
  }
  if (notification?.symbol) {
    return getPageHref("coin-details", { ...view, symbol: notification.symbol });
  }
  return null;
}
