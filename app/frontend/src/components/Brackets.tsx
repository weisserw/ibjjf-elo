import classNames from 'classnames'
import { useAppContext } from '../AppContext'
import BracketLive from './BracketLive'
import BracketRegistration from './BracketRegistration'

import "./Brackets.css"

export type Tabs = 'Live' | 'Registrations'

function Brackets() {
  const {
    bracketActiveTab,
    setBracketActiveTab,
  } = useAppContext()

  return (
      <div className="container">
        <div className="tabs">
          <ul>
            <li onClick={() => setBracketActiveTab('Live')} className={classNames({"is-active": bracketActiveTab === 'Live'})}><a>Live Brackets</a></li>
            <li onClick={() => setBracketActiveTab('Registrations')} className={classNames({"is-active": bracketActiveTab === 'Registrations'})}><a>Registrations</a></li>
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
          bracketActiveTab === 'Registrations' && (
            <p>
              This tool imports registrations from the IBJJF registration system and displays the current ratings of the competitors. To import a registration URL,
              find an event on <a href="https://ibjjf.com/" target="_blank" rel="nofollow noreferrer">ibjjf.com</a>, select "ATHLETES LIST BY DIVISIONS" from the event page,
              then copy and paste the URL from the browser address bar into the box below:
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
        <div className="notification mt-5">
          We cache responses from the IBJJF servers. If you don't see the latest data, try again in a few minutes.
        </div>
      </div>
  );
}
  
export default Brackets
