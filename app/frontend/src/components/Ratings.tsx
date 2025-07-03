import GiTabs from './GiTabs';
import EloTable from './EloTable';

function Ratings() {
  return (
    <section className="section py-0 has-background-light" style={{ minHeight: '100vh' }}>
      <div className="container no-mobile-padding">
        <div className="box no-mobile-radius" style={{ boxShadow: '0 2px 8px rgba(0,0,0,0.08)', borderRadius: '12px' }}>
          <GiTabs />
          <EloTable />
        </div>
      </div>
    </section>
  )
}

export default Ratings;
