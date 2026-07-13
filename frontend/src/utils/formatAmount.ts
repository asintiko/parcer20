export const formatAmount = (value: number | string | null | undefined): string => {
    if (value === null || value === undefined || value === '') return '—';

    const parsed = typeof value === 'number' ? value : parseFloat(String(value));
    if (Number.isNaN(parsed)) {
        return String(value);
    }

    return new Intl.NumberFormat('ru-RU', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    }).format(Math.abs(parsed));
};
