import {useState} from 'react';
import { useLocation } from 'react-router-dom';
import classNames from 'classnames';
import './Navbar.css';

function Navbar() {
  const [isMenuActive, setIsMenuActive] = useState(false);
  const location = useLocation();
  const activeLink = location.pathname;

  const getNavItemClass = (path: string) => classNames("navbar-item", {
    "is-active": activeLink === path,
    "has-background-link-80": activeLink === path
  });

  return (
    <nav className="navbar">
      <div className="navbar-brand">
        <h1 className="navbar-item">
          IBJJFRankings.com
        </h1>
        <a className={classNames("navbar-burger", {"is-active": isMenuActive})}
           onClick={() => setIsMenuActive(!isMenuActive)}>
          <span aria-hidden="true"></span>
          <span aria-hidden="true"></span>
          <span aria-hidden="true"></span>
          <span aria-hidden="true"></span>
        </a>
      </div>
      <div className={classNames("navbar-menu", {"is-active": isMenuActive})}>
        <div className="navbar-start">
          <a className={getNavItemClass("/")} href="/">
            Ratings
          </a>
          <a className={getNavItemClass("/database")} href="/database">
            Database
          </a>
          <a className={getNavItemClass("/about")} href="/about">
            About
          </a>
        </div>
      </div>
    </nav>
  );
}

export default Navbar;
