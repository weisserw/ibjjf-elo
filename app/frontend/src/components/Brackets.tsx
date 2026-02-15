import classNames from 'classnames'
import BracketLive from './BracketLive'
import BracketRegistration from './BracketRegistration'
import BracketArchive from './BracketArchive'
import BracketAwards from './BracketAwards'
import { t } from '../translate'
import { useNavigate } from 'react-router-dom'

import "./Brackets.css"

export type Tabs = 'Live' | 'Registrations' | 'Archive' | 'Awards'

interface BracketsProps {
  tab?: Tabs
}

function Brackets({ tab }: BracketsProps) {
  const navigate = useNavigate()

  return (
    <div className="container pl-2 pr-2">
      <div className="tabs">
        <ul>
          <li onClick={() => navigate('/tournaments')} className={classNames({"is-active": tab === 'Live'})}><a>{t("Live Brackets")}</a></li>
          <li onClick={() => navigate('/tournaments/registrations')} className={classNames({"is-active": tab === 'Registrations'})}><a>{t("Registrations")}</a></li>
          <li onClick={() => navigate('/tournaments/archive')} className={classNames({"is-active": tab === 'Archive'})}><a>{t("Archive")}</a></li>
          <li onClick={() => navigate('/tournaments/awards')} className={classNames({"is-active": tab === 'Awards'})}><a>{t("Team Awards")}</a></li>
        </ul>
      </div>
      {
        tab === 'Live' && (
          <p>
            {t("This tool imports brackets from")}{' '}<a href="https://bjjcompsystem.com/" target="_blank" rel="nofollow noreferrer">bjjcompsystem.com</a>{' '}{t("and displays the current ratings of the competitors. Brackets are typically posted 1-2 days before an event starts.")}
          </p>
        )
      }
      {
        tab === 'Archive' && (
          <p>
            {t("Search for a past event in our database to view brackets. Brackets are not available before December 2024.")}
          </p>
        )
      }
      {
        tab === 'Awards' && (
          <p>
            {t("Search for a past event in our database to view our team rankings based on match outcomes and opponent rating. To encourage competitive participation without pressure, white belts and teens are not included in team rankings.")}
          </p>
        )
      }
      {
        tab === 'Live' && (
          <BracketLive />
        )
      }
      {
        tab === 'Registrations' && (
          <BracketRegistration />
        )
      }
      {
        tab === 'Archive' && (
          <BracketArchive />
        )
      }
      {
        tab === 'Awards' && (
          <BracketAwards />
        )
      }
      {
        (tab === 'Live' || tab === 'Registrations') &&
          <div className="notification mt-5 content bracket-notification">
            <ul>
              <li>{t("We cache responses from the IBJJF servers. If you don't see the latest data, try again in a few minutes.")}</li>
              {
                tab === 'Live' && (
                  <li>
                    {t("Ratings shown are estimates and may differ from an athlete's final rating at the end of an event.")}
                  </li>
                )
              }
            </ul>
          </div>
      }
    </div>
  );
}

export default Brackets
