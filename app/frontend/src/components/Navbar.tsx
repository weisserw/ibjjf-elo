import { useState, useContext } from 'react';
import { useLocation, Link } from 'react-router-dom';
import classNames from 'classnames';
import logoImage from '/src/assets/logo.jpg'
import usFlag from '/src/assets/us_flag.png';
import brFlag from '/src/assets/br_flag.png';
import './Navbar.css';
import { AppContext } from '../AppContext';
import { t } from '../translate';

function Navbar() {
  const [isMenuActive, setIsMenuActive] = useState(false);
  const location = useLocation();
  const activeLink = location.pathname;
  const appContext = useContext(AppContext);
  const language = appContext?.language || 'en';
  const setLanguage = appContext?.setLanguage;

  const getNavItemClass = (path: string) => classNames("navbar-item", {
    "is-active": activeLink === path,
  });

  const handleLanguageSwitch = () => {
    if (setLanguage) setLanguage(language === 'en' ? 'pr' : 'en');
  };

  return (
    <nav className="navbar">
  <div className="navbar-brand custom-navbar-brand">
        <Link className="navbar-item logo" to="/">
          <img src={logoImage} alt="Logo" />
        </Link>
        <h1 className="navbar-item">
          {t("IBJJF Elo Rankings")}
        </h1>
        {/* Flex spacer for mobile to push button to right */}
  <span className="mobile-lang-switch flex-spacer"></span>
        {/* Mobile language button: left of burger, only on mobile */}
        <button
          className="navbar-item lang-switch mobile-lang-switch"
          onClick={handleLanguageSwitch}
          aria-label="Switch language"
        >
          <img
            src={language === 'en' ? usFlag : brFlag}
            alt={language === 'en' ? 'English' : 'Português'}
            className="lang-flag"
          />
        </button>
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
          <Link className={getNavItemClass("/")} to="/">
            {t("Ratings")}
          </Link>
          <Link className={getNavItemClass("/database")} to="/database">
            {t("Database")}
          </Link>
          <Link className={getNavItemClass("/tournaments")} to="/tournaments">
            {t("Tournaments")}
          </Link>
          <Link className={getNavItemClass("/calculator")} to="/calculator">
            {t("Calculator")}
          </Link>
          <Link className={getNavItemClass("/about")} to="/about">
            {t("About")}
          </Link>
        </div>
        <div className="navbar-end">
          {/* Desktop language button: far right, only on desktop */}
          <button
            className="navbar-item lang-switch desktop-lang-switch"
            onClick={handleLanguageSwitch}
            aria-label="Switch language"
          >
            <img
              src={language === 'en' ? usFlag : brFlag}
              alt={language === 'en' ? 'English' : 'Português'}
              className="lang-flag"
            />
          </button>
        </div>
      </div>
    </nav>
  );
}

export default Navbar;
