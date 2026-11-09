import { AlertCircle, LoaderCircle } from "lucide-react";

export function LoadingState({ label }: { label: string }) {
  return (
    <div aria-live="polite" className="state-card">
      <div>
        <LoaderCircle aria-hidden="true" className="loading-icon" size={20} />
        <strong>{label}</strong>
        <p>Retrieving tenant-scoped data from the commerce API.</p>
      </div>
    </div>
  );
}

export function ErrorState({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <div aria-live="assertive" className="state-card">
      <div>
        <AlertCircle
          aria-hidden="true"
          className="error-icon"
          size={21}
        />
        <strong>Reporting data is unavailable</strong>
        <p>{message}</p>
        <button
          className="button button-secondary button-small state-retry"
          onClick={onRetry}
          type="button"
        >
          Retry request
        </button>
      </div>
    </div>
  );
}
