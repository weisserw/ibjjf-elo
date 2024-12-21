import {useState} from 'react';
import classNames from 'classnames';
import './Navbar.css';

function Navbar() {
  const [isActive, setIsActive] = useState(false);

  return (
    <nav className="navbar">
      <div className="navbar-brand">
        <h1 className="navbar-item">
          IBJJF Elo Ratings
        </h1>
        <a className={classNames("navbar-burger", {"is-active": isActive})}
           onClick={() => setIsActive(!isActive)}>
          <span aria-hidden="true"></span>
          <span aria-hidden="true"></span>
          <span aria-hidden="true"></span>
          <span aria-hidden="true"></span>
        </a>
      </div>
      <div className={classNames("navbar-menu", {"is-active": isActive})}>
        <div className="navbar-start">
          <a className="navbar-item" href="/">
            Rankings
          </a>
          <a className="navbar-item" href="/database">
            Database
          </a>
          <a className="navbar-item" href="/about">
            About
          </a>
        </div>
      </div>
    </nav>
  );
}

export default Navbar;
