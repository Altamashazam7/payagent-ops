export function StatusBadge({ value }: { value: string }) {
  const tone =
    value === "won" || value === "paid" || value === "active"
      ? "success"
      : value === "critical" ||
          value === "overdue" ||
          value === "failed" ||
          value === "suspended" ||
          value === "lost"
        ? "danger"
        : value === "needs_response" ||
            value === "pending_approval" ||
            value === "under_review" ||
            value === "sent"
          ? "warning"
          : "neutral";

  return (
    <span className={`status-badge ${tone}`}>
      <span className="status-dot" />
      {value.replaceAll("_", " ")}
    </span>
  );
}
