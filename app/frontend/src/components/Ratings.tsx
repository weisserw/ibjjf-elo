import GiTabs, { type TabName } from './GiTabs';
import EloTable from './EloTable';
import type { FilterValues, OpenFilters } from './DBFilters';

interface RatingsProps {
  activeTab: TabName;
  gender: string
  age: string
  belt: string
  weight: string
  nameFilter: string
  page: number
  setGender: (value: string) => void
  setAge: (value: string) => void
  setBelt: (value: string) => void
  setWeight: (value: string) => void
  setNameFilter: (name: string) => void
  setActiveTab: (activeTab: TabName) => void
  setFilters: (filters: FilterValues) => void
  setOpenFilters: (openFilters: OpenFilters) => void
  setPage: (page: number) => void
}

function Ratings(props: RatingsProps) {
  return (
    <div className="container">
      <GiTabs setActiveTab={props.setActiveTab} activeTab={props.activeTab} />
      <EloTable gi={props.activeTab === 'Gi'}
                setFilters={props.setFilters}
                setOpenFilters={props.setOpenFilters}
                gender={props.gender}
                setGender={props.setGender}
                age={props.age}
                page={props.page}
                setAge={props.setAge}
                belt={props.belt}
                setBelt={props.setBelt}
                weight={props.weight}
                setWeight={props.setWeight}
                nameFilter={props.nameFilter}
                setNameFilter={props.setNameFilter}
                setPage={props.setPage}
                />
    </div>
  )
}

export default Ratings;
