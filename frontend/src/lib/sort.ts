// Client-side sorting for the small tables: numbers numerically, text in pt-BR order, empty cells always last.

export function sortBy<T>(rows: T[], get: (r: T) => number | string | null | undefined, desc: boolean): T[] {
  return [...rows].sort((a, b) => {
    const x = get(a), y = get(b);
    if (x == null && y == null) return 0;
    if (x == null) return 1;
    if (y == null) return -1;
    const c = typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y), "pt-BR");
    return desc ? -c : c;
  });
}
