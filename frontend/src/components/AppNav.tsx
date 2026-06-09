import { NAV_ITEMS, type AppPageId } from "../types/navigation";

interface AppNavProps {
  open: boolean;
  activePage: AppPageId;
  onNavigate: (page: AppPageId) => void;
  onClose: () => void;
}

export default function AppNav({ open, activePage, onNavigate, onClose }: AppNavProps) {
  return (
    <>
      {open && <button className="app-nav-backdrop" type="button" aria-label="关闭导航" onClick={onClose} />}
      <aside className={open ? "app-nav app-nav-open" : "app-nav"} aria-hidden={!open}>
        <div className="app-nav-header">
          <span>导航</span>
          <button className="icon-btn app-nav-close" type="button" onClick={onClose} aria-label="关闭导航">
            ×
          </button>
        </div>
        <nav className="app-nav-list">
          {NAV_ITEMS.map((item) => (
            <button
              key={item.id}
              className={activePage === item.id ? "app-nav-item active" : "app-nav-item"}
              type="button"
              onClick={() => {
                onNavigate(item.id);
                onClose();
              }}
            >
              <span className="app-nav-item-label">{item.label}</span>
              <span className="app-nav-item-desc">{item.description}</span>
            </button>
          ))}
        </nav>
      </aside>
    </>
  );
}
