import { createContext, useState, useContext, ReactNode } from 'react';
import type { FilterValues, OpenFilters } from './components/DBFilters';
import type { TabName } from './components/GiTabs';
import type {
  Event as BracketEvent,
  Category as BracketCategory,
  Gender as BracketGender,
  Competitor as BracketCompetitor,
  SortColumn as BracketSortColumn,
} from './components/Brackets';

interface AppContextProps {
  filters: FilterValues;
  setFilters: (filters: FilterValues) => void;
  openFilters: OpenFilters;
  setOpenFilters: (openFilters: OpenFilters) => void;
  activeTab: TabName;
  setActiveTab: (tab: TabName) => void;
  rankingGender: string;
  setRankingGender: (gender: string) => void;
  rankingAge: string;
  setRankingAge: (age: string) => void;
  rankingBelt: string;
  setRankingBelt: (belt: string) => void;
  rankingWeight: string;
  setRankingWeight: (weight: string) => void;
  rankingChanged: boolean;
  setRankingChanged: (changed: boolean) => void;
  rankingNameFilter: string;
  setRankingNameFilter: (nameFilter: string) => void;
  rankingPage: number;
  setRankingPage: (page: number) => void;
  dbPage: number;
  setDbPage: (page: number) => void;
  bracketEvents: BracketEvent[] | null;
  setBracketEvents: (events: BracketEvent[] | null) => void;
  bracketSelectedEvent: string | null;
  setBracketSelectedEvent: (event: string | null) => void;
  bracketGender: BracketGender;
  setBracketGender: (gender: BracketGender) => void;
  bracketCategories: BracketCategory[] | null;
  setBracketCategories: (categories: BracketCategory[] | null) => void;
  bracketSelectedCategory: string | null;
  setBracketSelectedCategory: (category: string | null) => void;
  bracketCompetitors: BracketCompetitor[] | null;
  setBracketCompetitors: (competitors: BracketCompetitor[] | null) => void;
  bracketSortColumn: BracketSortColumn;
  setBracketSortColumn: (column: BracketSortColumn) => void;
}

export const AppContext = createContext<AppContextProps | undefined>(undefined);

export const useAppContext = () => {
  const context = useContext(AppContext);
  if (!context) {
    throw new Error('useAppContext must be used within an AppProvider');
  }
  return context;
};

export const AppProvider = ({ children }: { children: ReactNode }) => {
  const [filters, setFilters] = useState<FilterValues>({});
  const [openFilters, setOpenFilters] = useState<OpenFilters>({ athlete: true, event: false, division: false });
  const [activeTab, setActiveTab] = useState<TabName>('Gi');
  const [rankingGender, setRankingGender] = useState('Male');
  const [rankingAge, setRankingAge] = useState('Adult');
  const [rankingBelt, setRankingBelt] = useState('BLACK');
  const [rankingWeight, setRankingWeight] = useState('');
  const [rankingChanged, setRankingChanged] = useState(false);
  const [rankingNameFilter, setRankingNameFilter] = useState('');
  const [rankingPage, setRankingPage] = useState(1);
  const [dbPage, setDbPage] = useState(1);
  const [bracketEvents, setBracketEvents] = useState<BracketEvent[] | null>(null)
  const [bracketSelectedEvent, setBracketSelectedEvent] = useState<string | null>(null)
  const [bracketGender, setBracketGender] = useState<BracketGender>('Male')
  const [bracketCategories, setBracketCategories] = useState<BracketCategory[] | null>(null)
  const [bracketSelectedCategory, setBracketSelectedCategory] = useState<string | null>(null)
  const [bracketCompetitors, setBracketCompetitors] = useState<BracketCompetitor[] | null>(null)
  const [bracketSortColumn, setBracketSortColumn] = useState<BracketSortColumn>('rating')

  return (
    <AppContext.Provider value={{
      filters, setFilters,
      openFilters, setOpenFilters,
      activeTab, setActiveTab,
      rankingGender, setRankingGender,
      rankingAge, setRankingAge,
      rankingBelt, setRankingBelt,
      rankingWeight, setRankingWeight,
      rankingChanged, setRankingChanged,
      rankingNameFilter, setRankingNameFilter,
      rankingPage, setRankingPage,
      dbPage, setDbPage,
      bracketEvents, setBracketEvents,
      bracketSelectedEvent, setBracketSelectedEvent,
      bracketGender, setBracketGender,
      bracketCategories, setBracketCategories,
      bracketSelectedCategory, setBracketSelectedCategory,
      bracketCompetitors, setBracketCompetitors,
      bracketSortColumn, setBracketSortColumn,
    }}>
      {children}
    </AppContext.Provider>
  );
};
