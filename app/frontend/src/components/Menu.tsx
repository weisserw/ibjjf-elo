import React, { useState, useRef } from "react";
import useClickOutside from "../hooks/useClickOutside";

import "./Menu.css"

interface MenuProps {
  wrapperClassName?: string;
  menuButton: {
    label: string;
    className?: string;
  }
  content: React.ReactNode;
}

// Note: This component uses Bulma dropdowns. If content contains nested dropdowns,
// they may be affected by the parent's is-active class. See DBFilters.css for fixes.
// 
// Alternative approach to avoid nested dropdowns:
// - Use a collapsible panel instead of dropdown
// - Use a modal/overlay for the content
// - Use tabs or accordion pattern
// - Use a custom dropdown implementation that doesn't rely on CSS classes
function Menu({ wrapperClassName, menuButton, content }: MenuProps) {
  const [showDropdown, setShowDropdown] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useClickOutside({
    ref: dropdownRef,
    callback: () => setShowDropdown(false),
    enabled: showDropdown
  });

  return (
    <div
      ref={dropdownRef}
      className={`dropdown${showDropdown ? " is-active" : ""} ${wrapperClassName}`}
      style={{ width: "100%" }}
    >
      <div className="dropdown-trigger" style={{ width: "100%" }}>
        <button
          className="button is-fullwidth is-outlined is-link"
          aria-haspopup="true"
          aria-controls="dropdown-menu"
          onClick={() => setShowDropdown((v) => !v)}
        >
          <span>{menuButton.label}</span>
          <span className="icon is-small">
            <i className={`fas ${showDropdown ? "fa-angle-up" : "fa-angle-down"}`} aria-hidden="true"></i>
          </span>
        </button>
      </div>
      <div className="dropdown-menu" id="dropdown-menu" role="menu" style={{ width: "100%" }}>
        <div className="dropdown-content" style={{ padding: "1rem", width: "100%" }}>
          {content}
        </div>
      </div>
    </div>
  );
}

export default Menu;