import { createContext, useState, useContext, useCallback, ReactNode } from 'react';
import type { FilterValues, OpenFilters } from './components/DBFilters';
import type { TabName } from './components/GiTabs';
import type {
  Tabs as BracketTabs,
} from './components/Brackets';
import type {
  Event as BracketEvent,
  Category as BracketCategory,
} from './components/BracketLive';
import type {
  SortColumn as BracketSortColumn,
} from './components/BracketTable';
import type {
  Competitor as BracketCompetitor,
} from './components/BracketUtils';

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
  bracketCategories: BracketCategory[] | null;
  setBracketCategories: (categories: BracketCategory[] | null) => void;
  bracketSelectedCategory: string | null;
  setBracketSelectedCategory: (category: string | null) => void;
  bracketCompetitors: BracketCompetitor[] | null;
  setBracketCompetitors: (competitors: BracketCompetitor[] | null) => void;
  bracketSortColumn: BracketSortColumn;
  setBracketSortColumn: (column: BracketSortColumn) => void;
  bracketActiveTab: BracketTabs;
  setBracketActiveTab: (tab: BracketTabs) => void;
  bracketRegistrationUrl: string;
  setBracketRegistrationUrl: (url: string) => void;
  bracketRegistrationEventName: string;
  setBracketRegistrationEventName: (name: string) => void;
  bracketRegistrationEventTotal: number | null;
  setBracketRegistrationEventTotal: (total: number | null) => void;
  bracketRegistrationEventUrl: string;
  setBracketRegistrationEventUrl: (url: string) => void;
  bracketRegistrationCategories: string[] | null;
  setBracketRegistrationCategories: (categories: string[] | null) => void;
  bracketRegistrationSelectedCategory: string | null;
  setBracketRegistrationSelectedCategory: (category: string | null) => void;
  bracketRegistrationCompetitors: BracketCompetitor[] | null;
  setBracketRegistrationCompetitors: (competitors: BracketCompetitor[] | null) => void;
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
  const [bracketCategories, setBracketCategories] = useState<BracketCategory[] | null>(null)
  const [bracketSelectedCategory, setBracketSelectedCategory] = useState<string | null>(null)
  const [bracketCompetitors, setBracketCompetitors] = useState<BracketCompetitor[] | null>(null)
  const [bracketSortColumn, setBracketSortColumn] = useState<BracketSortColumn>('rating')
  const [bracketActiveTab, setBracketActiveTab] = useState<BracketTabs>('Live')
  const [bracketRegistrationUrl, setBracketRegistrationUrl] = useState('')
  const [bracketRegistrationEventName, setBracketRegistrationEventName] = useState('')
  const [bracketRegistrationEventTotal, setBracketRegistrationEventTotal] = useState<number | null>(null)
  const [bracketRegistrationEventUrl, setBracketRegistrationEventUrl] = useState('')
  const [bracketRegistrationCategories, setBracketRegistrationCategories] = useState<string[] | null>(null)
  const [bracketRegistrationSelectedCategory, setBracketRegistrationSelectedCategory] = useState<string | null>(null)
  const [bracketRegistrationCompetitors, setBracketRegistrationCompetitors] = useState<BracketCompetitor[] | null>(null)

  const updateFilters = useCallback((newFilters: FilterValues) => {
    // Reset the page when filters change
    setDbPage(1);
    setFilters(newFilters);
  }, []);

  return (
    <AppContext.Provider value={{
      filters, setFilters: updateFilters,
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
      bracketCategories, setBracketCategories,
      bracketSelectedCategory, setBracketSelectedCategory,
      bracketCompetitors, setBracketCompetitors,
      bracketSortColumn, setBracketSortColumn,
      bracketActiveTab, setBracketActiveTab,
      bracketRegistrationUrl, setBracketRegistrationUrl,
      bracketRegistrationEventName, setBracketRegistrationEventName,
      bracketRegistrationEventTotal, setBracketRegistrationEventTotal,
      bracketRegistrationEventUrl, setBracketRegistrationEventUrl,
      bracketRegistrationCategories, setBracketRegistrationCategories,
      bracketRegistrationSelectedCategory, setBracketRegistrationSelectedCategory,
      bracketRegistrationCompetitors, setBracketRegistrationCompetitors,
    }}>
      {children}
    </AppContext.Provider>
  );
};
