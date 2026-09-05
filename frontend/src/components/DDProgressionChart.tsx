import DDWorkspace from './DDWorkspace'

// Kept as the dashboard import contract while the data source moves from the
// legacy journey aggregate to the live, versioned DD calculation.
function DDProgressionChart() {
  return <DDWorkspace compact />
}

export default DDProgressionChart
