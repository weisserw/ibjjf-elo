import GiTabs from './GiTabs';
import DBTable from './DBTable';

function Database() {
  return (
    <section className="section py-0 has-background-light" style={{ minHeight: '100vh' }}>
      <div className="container">
        <div className="box" style={{ boxShadow: '0 2px 8px rgba(0,0,0,0.08)', borderRadius: '12px' }}>
          <GiTabs />
          <DBTable />
        </div>
      </div>
    </section>
  )
}

export default Database;
