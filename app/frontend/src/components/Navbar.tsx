import { useState, useContext, useMemo, useEffect, type FormEvent } from 'react';
import { useLocation, Link, useNavigate } from 'react-router-dom';
import classNames from 'classnames';
import Autosuggest from 'react-autosuggest';
import debounce from 'lodash/debounce';
import axios from 'axios';
import logoImage from '/src/assets/logo.png'
import enIcon from '/src/assets/icon-en.svg';
import ptIcon from '/src/assets/icon-pt.svg';
import './Navbar.css';
import { AppContext } from '../AppContext';
import { t } from '../translate';
import { axiosErrorToast, renderAthleteSuggestion, type AthleteSuggestion } from '../utils';

function Navbar() {
  const [isMenuActive, setIsMenuActive] = useState(false);
  const [isSearchOpen, setIsSearchOpen] = useState(false);
  const [athleteName, setAthleteName] = useState('');
  const [athleteSuggestions, setAthleteSuggestions] = useState<AthleteSuggestion[]>([]);
  const location = useLocation();
  const navigate = useNavigate();
  const activeLink = location.pathname;
  const appContext = useContext(AppContext);
  const language = appContext?.language || 'en';
  const setLanguage = appContext?.setLanguage;
  const activeTab = appContext?.activeTab || 'Gi';
  const isMoreActive = ["/calculator", "/news", "/about"].includes(activeLink);

  const getNavItemClass = (path: string, startsWith?: boolean) => classNames("navbar-item", {
    "is-active": startsWith ? activeLink.startsWith(path) : activeLink === path,
  });

  const handleLanguageSwitch = (e: React.MouseEvent) => {
    e.preventDefault();
    if (setLanguage) setLanguage(language === 'en' ? 'pt' : 'en');
  };

  const debouncedGetAthleteSuggestions = useMemo(
    () => debounce(async ({ value }: { value: string }) => {
      if (!value.trim()) {
        setAthleteSuggestions([]);
        return;
      }

      try {
        const response = await axios.get(`/api/athletes?search=${encodeURIComponent(value)}`);
        setAthleteSuggestions(response.data);
      } catch (error) {
        axiosErrorToast(error);
      }
    }, 300, { trailing: true }),
    []
  );

  useEffect(() => {
    return () => {
      debouncedGetAthleteSuggestions.cancel();
    };
  }, [debouncedGetAthleteSuggestions]);

  useEffect(() => {
    const onDocumentMouseDown = (event: MouseEvent) => {
      const target = event.target as Element | null;
      if (!target?.closest('.navbar-search-wrapper')) {
        setIsSearchOpen(false);
      }
    };

    document.addEventListener('mousedown', onDocumentMouseDown);
    return () => document.removeEventListener('mousedown', onDocumentMouseDown);
  }, []);

  useEffect(() => {
    setIsSearchOpen(false);
  }, [activeLink]);

  useEffect(() => {
    if (!isSearchOpen) {
      return;
    }

    const animationFrameId = window.requestAnimationFrame(() => {
      const searchInputs = Array.from(
        document.querySelectorAll<HTMLInputElement>('.navbar-search-popup.is-open .navbar-search-input')
      );
      const visibleInput = searchInputs.find((input) => input.offsetParent !== null);
      (visibleInput ?? searchInputs[0])?.focus();
    });

    return () => window.cancelAnimationFrame(animationFrameId);
  }, [isSearchOpen]);

  const onAthleteSelected = async (suggestion: AthleteSuggestion) => {
    const slug = suggestion.slug;
    if (slug) {
      navigate(`/athlete/${encodeURIComponent(slug)}`);
      return;
    }

    try {
      const response = await axios.get('/api/athletes/ratings', {
        params: {
          name: suggestion.name,
          gi: activeTab === 'Gi' ? 'true' : 'false',
        },
      });
      if (response.data?.slug) {
        navigate(`/athlete/${encodeURIComponent(response.data.slug)}`);
      }
    } catch (error) {
      axiosErrorToast(error);
    }
  };

  const searchAutosuggest = (
    <Autosuggest
      suggestions={athleteSuggestions}
      onSuggestionsFetchRequested={debouncedGetAthleteSuggestions}
      onSuggestionsClearRequested={() => setAthleteSuggestions([])}
      multiSection={false}
      getSuggestionValue={(suggestion) => suggestion.name}
      renderSuggestion={renderAthleteSuggestion}
      onSuggestionSelected={(_event: FormEvent<HTMLElement>, { suggestion }: { suggestion: AthleteSuggestion }) => {
        setAthleteName('');
        setAthleteSuggestions([]);
        setIsSearchOpen(false);
        void onAthleteSelected(suggestion);
      }}
      inputProps={{
        className: 'input navbar-search-input',
        value: athleteName,
        placeholder: t('Find Athlete'),
        onChange: (_event: FormEvent<HTMLElement>, { newValue }: { newValue: string }) => setAthleteName(newValue),
      }}
    />
  );

  return (
    <nav className="navbar">
      <div className="navbar-brand custom-navbar-brand">
        <Link className="navbar-item logo" to="/">
          <img src={logoImage} alt="Logo" />
        </Link>
        <h1 className={classNames("navbar-item", {pt: language === 'pt'})}>
          {t("Unofficial IBJJF Rankings")}
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
          <Link className={getNavItemClass("/awards")} to="/awards">
            {t("Awards")}
          </Link>
          <Link className={classNames(getNavItemClass("/calculator"), "mobile-only")} to="/calculator">
            {t("Calculator")}
          </Link>
          <Link className={classNames(getNavItemClass("/news"), "mobile-only")} to="/news">
            {t("News")}
          </Link>
          <Link className={classNames(getNavItemClass("/about"), "mobile-only")} to="/about">
            {t("About")}
          </Link>
          <Link className={classNames(getNavItemClass("/calculator"), "wide-desktop-only")} to="/calculator">
            {t("Calculator")}
          </Link>
          <Link className={classNames(getNavItemClass("/news"), "wide-desktop-only")} to="/news">
            {t("News")}
          </Link>
          <Link className={classNames(getNavItemClass("/about"), "wide-desktop-only")} to="/about">
            {t("About")}
          </Link>
          <div className="navbar-item has-dropdown is-hoverable desktop-only compact-desktop-only">
            <span
              className={classNames("navbar-link is-arrowless", {
              "is-active": isMoreActive,
              })}
              aria-label="More navigation"
              title="More"
            >
              ...
            </span>
            <div className="navbar-dropdown">
              <Link className={getNavItemClass("/calculator")} to="/calculator">
                {t("Calculator")}
              </Link>
              <Link className={getNavItemClass("/news")} to="/news">
                {t("News")}
              </Link>
              <Link className={getNavItemClass("/about")} to="/about">
                {t("About")}
              </Link>
            </div>
          </div>
          <div className="navbar-item mobile-only navbar-search-wrapper mobile-navbar-search-wrapper">
            <button
              className="lang-switch navbar-search-trigger"
              aria-label="Search athletes"
              type="button"
              onClick={() => setIsSearchOpen((value) => !value)}
            >
              <span className="icon">
                <i className="fas fa-search" aria-hidden="true"></i>
              </span>
            </button>
            <div className={classNames('navbar-search-popup', { 'is-open': isSearchOpen })}>
              {searchAutosuggest}
            </div>
          </div>
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
          <div className="navbar-item desktop-only navbar-search-wrapper">
            <button
              className="lang-switch navbar-search-trigger"
              aria-label="Search athletes"
              type="button"
              onClick={() => setIsSearchOpen((value) => !value)}
            >
              <span className="icon">
                <i className="fas fa-search" aria-hidden="true"></i>
              </span>
            </button>
            <div className={classNames('navbar-search-popup', { 'is-open': isSearchOpen })}>
              {searchAutosuggest}
            </div>
          </div>
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
