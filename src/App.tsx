import { Dashboard } from './components/Dashboard';
import { InvestmentBrain } from './components/InvestmentBrain';

function App() {
  const path = window.location.pathname.replace(/\/$/, '');

  if (path === '/dashboard/brain') {
    return <InvestmentBrain />;
  }

  return (
    <Dashboard />
  );
}

export default App;
