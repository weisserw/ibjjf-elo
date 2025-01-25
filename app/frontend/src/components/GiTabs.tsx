import classNames from "classnames"
import { useAppContext } from "../AppContext"

export type TabName = 'Gi' | 'No Gi'

function GiTabs() {
  const { activeTab, setActiveTab } = useAppContext()
  return (
    <div className="tabs">
      <ul>
        <li onClick={() => setActiveTab('Gi')} className={classNames({"is-active": activeTab === 'Gi'})}><a>Gi</a></li>
        <li onClick={() => setActiveTab('No Gi')} className={classNames({"is-active": activeTab === 'No Gi'})}><a>No Gi</a></li>
      </ul>
    </div>
  )
}

export default GiTabs;