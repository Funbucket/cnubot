import { adminSections } from "@/lib/admin-navigation";
import { Icon } from "./icon";

export function AdminNavigation({ current }: { current: string }) {
  return (
    <nav className="admin-navigation" aria-label="관리자 메뉴">
      {adminSections.map((item) => (
        <a key={item.key} href={item.href} className={item.key === current ? "active" : ""} aria-current={item.key === current ? "page" : undefined}>
          <Icon name={item.icon} className="nav-icon" />{item.label}
        </a>
      ))}
    </nav>
  );
}
