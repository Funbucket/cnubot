import type { Row } from "./reports";

export function csvCell(value: unknown) {
  let text = String(value ?? "");
  if (/^[\s]*[=+\-@\t\r\n]/.test(text)) text = "'" + text;
  return '"' + text.replaceAll('"', '""') + '"';
}
export function productCSV(rows: Row[]) {
  const fields = [
    "product_name",
    "category_name",
    "product_key",
    "exposed_users",
    "clicked_users",
    "click_events",
  ];
  return (
    "\uFEFF" +
    [
      ["상품", "카테고리", "상품 ID", "노출 사용자", "클릭 사용자", "클릭 횟수"]
        .map(csvCell)
        .join(","),
      ...rows.map((row) => fields.map((key) => csvCell(row[key])).join(",")),
    ].join("\r\n")
  );
}
