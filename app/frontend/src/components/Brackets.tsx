import classNames from 'classnames'
import { useAppContext } from '../AppContext'
import BracketLive from './BracketLive'
import BracketRegistration from './BracketRegistration'
import BracketArchive from './BracketArchive'

import "./Brackets.css"

export type Tabs = 'Live' | 'Registrations' | 'Archive'

function Brackets() {
  const {
    bracketActiveTab,
    setBracketActiveTab,
  } = useAppContext()

  return (
    <section className="section has-background-light py-0" style={{ minHeight: '100vh' }}>
      <div className="container">
        <div className="box" style={{ boxShadow: '0 2px 8px rgba(0,0,0,0.08)', borderRadius: '12px' }}>
          <div className="tabs">
            <ul>
              <li onClick={() => setBracketActiveTab('Live')} className={classNames({"is-active": bracketActiveTab === 'Live'})}><a>Live Brackets</a></li>
              <li onClick={() => setBracketActiveTab('Registrations')} className={classNames({"is-active": bracketActiveTab === 'Registrations'})}><a>Registrations</a></li>
              <li onClick={() => setBracketActiveTab('Archive')} className={classNames({"is-active": bracketActiveTab === 'Archive'})}><a>Archive</a></li>
            </ul>
          </div>
          {
            bracketActiveTab === 'Live' && (
              <p>
                This tool imports brackets from <a href="https://bjjcompsystem.com/" target="_blank" rel="nofollow noreferrer">bjjcompsystem.com</a> and displays the current ratings of the competitors.
                Brackets are typically posted 1-2 days before an event starts.
              </p>
            )
          }
          {
            bracketActiveTab === 'Archive' && (
              <p>
                Search for a past event in our database to view brackets. Brackets are not available before December 2024.
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
                  <li>We cache responses from the IBJJF servers. If you don't see the latest data, try again in a few minutes.</li>
                  {
                    bracketActiveTab === 'Live' && (
                      <li>
                        Ratings shown are estimates and may differ from an athlete's final rating at the end of an event.
                      </li>
                    )
                  }
                </ul>
              </div>
          }
        </div>
      </div>
    </section>
  );
}
  
export default Brackets
