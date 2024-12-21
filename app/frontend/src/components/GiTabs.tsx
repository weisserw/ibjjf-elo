import classNames from "classnames"

interface GiTabsProps {
  setActiveTab: (tab: string) => void
  activeTab: string
}

function GiTabs(props: GiTabsProps) {
  return (
    <div className="tabs">
      <ul>
        <li onClick={() => props.setActiveTab('Gi')} className={classNames({"is-active": props.activeTab === 'Gi'})}><a>Gi</a></li>
        <li onClick={() => props.setActiveTab('No Gi')} className={classNames({"is-active": props.activeTab === 'No Gi'})}><a>No Gi</a></li>
      </ul>
    </div>
  )
}

export default GiTabs;