/**
 * Broker result sort order:
 *   1. Violations (most violations first, then alphabetical)
 *   2. Clear (alphabetical)
 *   3. Cancelled (alphabetical)
 *   4. Failed (alphabetical)
 */

interface Sortable {
  name: string;
  violationCount: number;
  isCancelled: boolean;
  isFailed: boolean;
}

function sortGroup(item: Sortable): number {
  if (item.violationCount > 0) return 0;
  if (!item.isCancelled && !item.isFailed) return 1; // clear
  if (item.isCancelled) return 2;
  return 3; // failed
}

export function compareBrokerResults(a: Sortable, b: Sortable): number {
  const groupA = sortGroup(a);
  const groupB = sortGroup(b);
  if (groupA !== groupB) return groupA - groupB;
  if (groupA === 0 && a.violationCount !== b.violationCount) {
    return b.violationCount - a.violationCount;
  }
  return a.name.localeCompare(b.name);
}
