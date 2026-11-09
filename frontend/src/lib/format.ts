export function formatCurrency(amount: string, currency: string): string {
  const parsed = /^(-?)(\d+)(?:\.(\d+))?$/.exec(amount);
  if (!parsed) {
    return `${currency} ${amount}`;
  }
  const [, sign, wholePart, fractionPart = ""] = parsed;
  const formatter = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
  });
  const [currencyPart] = formatter
    .formatToParts(0)
    .filter((part) => part.type === "currency");
  const whole = wholePart.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const fractionDigits =
    formatter.resolvedOptions().minimumFractionDigits ?? 2;
  const fraction = fractionPart.padEnd(fractionDigits, "0");
  const decimals = fraction ? `.${fraction}` : "";
  const symbol = currencyPart?.value ?? currency;
  return `${sign}${symbol}${whole}${decimals}`;
}

export function formatDate(value: string | null): string {
  if (!value) {
    return "—";
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "—"
    : new Intl.DateTimeFormat("en", {
        month: "short",
        day: "numeric",
        year: "numeric",
      }).format(date);
}
