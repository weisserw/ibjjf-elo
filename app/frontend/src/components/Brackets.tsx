import classNames from 'classnames'
import { useAppContext } from '../AppContext'
import BracketLive from './BracketLive'
import BracketRegistration from './BracketRegistration'
import BracketArchive from './BracketArchive'
import { t } from '../translate'

import "./Brackets.css"

export type Tabs = 'Live' | 'Registrations' | 'Archive'

function Brackets() {
  const {
    bracketActiveTab,
    setBracketActiveTab,
  } = useAppContext()

  return (
    <div className="container pl-2 pr-2">
      <div className="tabs">
        <ul>
          <li onClick={() => setBracketActiveTab('Live')} className={classNames({"is-active": bracketActiveTab === 'Live'})}><a>{t("Live Brackets")}</a></li>
          <li onClick={() => setBracketActiveTab('Registrations')} className={classNames({"is-active": bracketActiveTab === 'Registrations'})}><a>{t("Registrations")}</a></li>
          <li onClick={() => setBracketActiveTab('Archive')} className={classNames({"is-active": bracketActiveTab === 'Archive'})}><a>{t("Archive")}</a></li>
        </ul>
      </div>
      {
        bracketActiveTab === 'Live' && (
          <p>
            {t("This tool imports brackets from")}{' '}<a href="https://bjjcompsystem.com/" target="_blank" rel="nofollow noreferrer">bjjcompsystem.com</a>{' '}{t("and displays the current ratings of the competitors. Brackets are typically posted 1-2 days before an event starts.")}
          </p>
        )
      }
      {
        bracketActiveTab === 'Archive' && (
          <p>
            {t("Search for a past event in our database to view brackets. Brackets are not available before December 2024.")}
          </p>
        )
      }
      {
        bracketActiveTab === 'Live' && (
          <BracketLive />
        )
      }
      {
        bracketActiveTab === 'Registrations' && (
          <BracketRegistration />
        )
      }
      {
        bracketActiveTab === 'Archive' && (
          <BracketArchive />
        )
      }
      {
        (bracketActiveTab === 'Live' || bracketActiveTab === 'Registrations') &&
          <div className="notification mt-5 content bracket-notification">
            <ul>
              <li>{t("We cache responses from the IBJJF servers. If you don't see the latest data, try again in a few minutes.")}</li>
              {
                bracketActiveTab === 'Live' && (
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
