function EloTable() {
  return (
    <table className="table is-fullwidth is-striped">
      <thead>
        <tr>
          <th>Rank</th>
          <th>Name</th>
          <th>Elo</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>1</td>
          <td>John Doe</td>
          <td>2400</td>
        </tr>
        <tr>
          <td>2</td>
          <td>Jane Smith</td>
          <td>2300</td>
        </tr>
      </tbody>
    </table>
  )
}

export default EloTable
