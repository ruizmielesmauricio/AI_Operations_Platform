// A minimal same-tab event bus so the Notification Centre page and
// AppNav's unread badge can agree on "something just changed" without a
// shared state library — this app has none, and one component for one
// cross-component signal isn't worth introducing one. Found live: after
// mark-read/mark-all-read/dismiss on /notifications, the AppNav badge
// stayed stale until its own 60s poll happened to fire, which read as a
// real inconsistency (the page said 0 unread, the nav said 1). No
// WebSockets/SSE — per explicit instruction, this is still just a
// same-tab, in-memory nudge to poll sooner, not a push channel.
const EVENT_NAME = "orla:notifications-changed";

export function broadcastNotificationsChanged(): void {
  window.dispatchEvent(new Event(EVENT_NAME));
}

export function onNotificationsChanged(handler: () => void): () => void {
  window.addEventListener(EVENT_NAME, handler);
  return () => window.removeEventListener(EVENT_NAME, handler);
}
