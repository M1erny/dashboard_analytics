import { Dashboard } from './components/Dashboard';
import { InvestmentBrainChat } from './components/InvestmentBrainChat';

function App() {
  const path = window.location.pathname.replace(/\/$/, '');

  if (path === '/dashboard/brain') {
    return <InvestmentBrainChat />;
  }

  return (
    <Dashboard />
  );
}

export default App;
