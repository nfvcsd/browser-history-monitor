export const browserTimezone = () => Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
export function localDate(value: Date) {
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
}
