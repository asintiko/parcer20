import React from 'react';
import './CurrencyTabs.css';

/**
 * Компонент переключения между валютными вкладками (UZS / USD)
 * Используется для разделения транзакций по валютам в отдельные листы
 */
interface CurrencyTabsProps {
  activeCurrency: 'UZS' | 'USD';
  onCurrencyChange: (currency: 'UZS' | 'USD') => void;
  uzsCount?: number;
  usdCount?: number;
}

const CurrencyTabs: React.FC<CurrencyTabsProps> = ({
  activeCurrency,
  onCurrencyChange,
  uzsCount = 0,
  usdCount = 0
}) => {
  return (
    <div className="currency-tabs-container">
      <div className="currency-tabs">
        <button
          className={`currency-tab ${activeCurrency === 'UZS' ? 'active' : ''}`}
          onClick={() => onCurrencyChange('UZS')}
          type="button"
        >
          <span className="currency-tab-label">UZS</span>
          {uzsCount > 0 && (
            <span className="currency-tab-count">{uzsCount.toLocaleString()}</span>
          )}
        </button>

        <button
          className={`currency-tab ${activeCurrency === 'USD' ? 'active' : ''}`}
          onClick={() => onCurrencyChange('USD')}
          type="button"
        >
          <span className="currency-tab-label">USD</span>
          {usdCount > 0 && (
            <span className="currency-tab-count">{usdCount.toLocaleString()}</span>
          )}
        </button>
      </div>
    </div>
  );
};

export default CurrencyTabs;
