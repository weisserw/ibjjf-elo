import { useEffect, useRef, useState } from 'react';
import { useLocation, Link } from 'react-router-dom';
import classNames from 'classnames';
import logoImage from '/src/assets/logo.jpg'
import './Navbar.css';

function NavItem({ path, label, setIsMenuActive, getNavItemClass }: { path: string, label: string, setIsMenuActive: (value: boolean) => void, getNavItemClass: (path: string) => string }) {
  return (
    <div className="is-flex" onClick={() => setIsMenuActive(false)}>
      <Link className={getNavItemClass(path)} to={path}>{label}</Link>
    </div>
  )
}

function Navbar() {
  const [isMenuActive, setIsMenuActive] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const location = useLocation();
  const activeLink = location.pathname;

  const getNavItemClass = (path: string) => classNames("navbar-item", {
    "is-active": activeLink === path,
  });

  useEffect(() => {
    if (!isMenuActive) return;
    function handleClickOutside(event: MouseEvent) {
      if (
        menuRef.current &&
        !menuRef.current.contains(event.target as Node)
      ) {
        setIsMenuActive(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [isMenuActive]);

  return (
    <nav className="navbar has-background-light" style={{ boxShadow: '0 2px 8px rgba(0,0,0,0.08)', borderRadius: '12px', marginBottom: '2rem', padding: '0.5rem 1.5rem' }}>
      <div className="navbar-brand">
        <Link className="navbar-item logo" to="/">
          <img src={logoImage} alt="Logo" />
        </Link>
        <h1 className="navbar-item">
          IBJJF Elo Rankings
        </h1>
        <a className={classNames("navbar-burger", { "is-active": isMenuActive })}
          onClick={() => setIsMenuActive(!isMenuActive)}>
          <span aria-hidden="true"></span>
          <span aria-hidden="true"></span>
          <span aria-hidden="true"></span>
          <span aria-hidden="true"></span>
        </a>
      </div>
      <div ref={menuRef} className={classNames("navbar-menu", { "is-active": isMenuActive })}>
        <div className="navbar-start">
          <NavItem path="/" label="Ratings" setIsMenuActive={setIsMenuActive} getNavItemClass={getNavItemClass} />
          <NavItem path="/database" label="Database" setIsMenuActive={setIsMenuActive} getNavItemClass={getNavItemClass} />
          <NavItem path="/brackets" label="Brackets" setIsMenuActive={setIsMenuActive} getNavItemClass={getNavItemClass} />
          <NavItem path="/calculator" label="Calculator" setIsMenuActive={setIsMenuActive} getNavItemClass={getNavItemClass} />
          <NavItem path="/about" label="About" setIsMenuActive={setIsMenuActive} getNavItemClass={getNavItemClass} />
        </div>
      </div>
    </nav>
  );
}

export default Navbar;
