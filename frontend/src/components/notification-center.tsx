"use client";

import { Bell } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { z } from "zod";

const notificationSchema = z.object({
  event_id: z.string().uuid(),
  event_type: z.literal("notification.created"),
  occurred_at: z.string().datetime({ offset: true }),
  payload: z.object({
    title: z.string().min(1).max(120),
    message: z.string().min(1).max(500),
    severity: z.enum(["info", "success", "warning", "error"]),
    href: z
      .string()
      .refine(
        (value) =>
          value.startsWith("/") &&
          !value.startsWith("//") &&
          !value.includes("\\") &&
          !value.includes("\r") &&
          !value.includes("\n"),
      )
      .nullable(),
  }),
});

type NotificationEvent = z.infer<typeof notificationSchema>;

export function NotificationCenter() {
  const [connected, setConnected] = useState(false);
  const [open, setOpen] = useState(false);
  const [notifications, setNotifications] = useState<NotificationEvent[]>([]);

  useEffect(() => {
    const stream = new EventSource("/api/backend/events/stream");
    const onOpen = () => setConnected(true);
    const onError = () => setConnected(false);
    const onNotification = (event: Event) => {
      if (!(event instanceof MessageEvent) || typeof event.data !== "string") {
        return;
      }
      let raw: unknown;
      try {
        raw = JSON.parse(event.data);
      } catch {
        console.error("Discarded malformed realtime notification JSON");
        return;
      }
      const parsed = notificationSchema.safeParse(raw);
      if (!parsed.success) {
        console.error("Discarded invalid realtime notification envelope");
        return;
      }
      setNotifications((current) => [
        parsed.data,
        ...current.filter((item) => item.event_id !== parsed.data.event_id),
      ].slice(0, 5));
    };

    stream.addEventListener("open", onOpen);
    stream.addEventListener("error", onError);
    stream.addEventListener("notification.created", onNotification);
    return () => {
      stream.removeEventListener("open", onOpen);
      stream.removeEventListener("error", onError);
      stream.removeEventListener("notification.created", onNotification);
      stream.close();
    };
  }, []);

  return (
    <div className="notification-center">
      <button
        aria-expanded={open}
        aria-label={`Notifications${notifications.length ? `, ${notifications.length} recent` : ""}`}
        className="notification-trigger"
        onClick={() => setOpen((current) => !current)}
        type="button"
      >
        <Bell aria-hidden="true" size={15} />
        <span>{connected ? "LIVE" : "RECONNECTING"}</span>
        {notifications.length > 0 && (
          <span className="notification-count">{notifications.length}</span>
        )}
      </button>
      {open && (
        <section
          aria-label="Recent notifications"
          className="notification-popover"
        >
          <strong>Recent notifications</strong>
          {notifications.length === 0 ? (
            <p aria-live="polite">No new notifications.</p>
          ) : (
            <ul aria-live="polite">
              {notifications.map(({ event_id, payload, occurred_at }) => (
                <li key={event_id}>
                  <span className={`notification-severity ${payload.severity}`} />
                  <div>
                    {payload.href ? (
                      <Link href={payload.href}>{payload.title}</Link>
                    ) : (
                      <strong>{payload.title}</strong>
                    )}
                    <p>{payload.message}</p>
                    <time dateTime={occurred_at}>
                      {new Intl.DateTimeFormat("en", {
                        hour: "numeric",
                        minute: "2-digit",
                      }).format(new Date(occurred_at))}
                    </time>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </div>
  );
}
