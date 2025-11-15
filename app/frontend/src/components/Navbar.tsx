import { useState, useContext } from 'react';
import { useLocation, Link } from 'react-router-dom';
import classNames from 'classnames';
import logoImage from '/src/assets/logo.jpg'
import enIcon from '/src/assets/icon-en.svg';
import ptIcon from '/src/assets/icon-pt.svg';
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

  const getNavItemClass = (path: string, startsWith?: boolean) => classNames("navbar-item", {
    "is-active": startsWith ? activeLink.startsWith(path) : activeLink === path,
  });

  const handleLanguageSwitch = (e: React.MouseEvent) => {
    e.preventDefault();
    if (setLanguage) setLanguage(language === 'en' ? 'pt' : 'en');
  };

  return (
    <nav className="navbar">
      <div className="navbar-brand custom-navbar-brand">
        <Link className="navbar-item logo" to="/">
          <img src={logoImage} alt="Logo" />
        </Link>
        <h1 className={classNames("navbar-item", {pt: language === 'pt'})}>
          {t("IBJJF Elo Rankings")}
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
          <Link className={getNavItemClass("/")} to="/">
            {t("Ratings")}
          </Link>
          <Link className={getNavItemClass("/database")} to="/database">
            {t("Database")}
          </Link>
          <Link className={getNavItemClass("/tournaments", true)} to="/tournaments">
            {t("Tournaments")}
          </Link>
          <Link className={getNavItemClass("/calculator")} to="/calculator">
            {t("Calculator")}
          </Link>
          <Link className={getNavItemClass("/about")} to="/about">
            {t("About")}
          </Link>
          <button
            className="navbar-item lang-switch mobile-lang-switch mobile-only"
            onClick={handleLanguageSwitch}
            aria-label="Switch language"
          >
            <img
              src={language === 'en' ? enIcon : ptIcon}
              alt={language === 'en' ? 'English' : 'Português'}
              className="lang-icon"
            />
          </button>
        </div>
        <div className="navbar-end">
          <button
            className="navbar-item lang-switch desktop-lang-switch"
            onClick={handleLanguageSwitch}
            aria-label="Switch language"
          >
            <img
              src={language === 'en' ? enIcon : ptIcon}
              alt={language === 'en' ? 'English' : 'Português'}
              className="lang-icon"
            />
          </button>
        </div>
      </div>
    </nav>
  );
}

export default Navbar;
