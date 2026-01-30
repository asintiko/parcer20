/**
 * Date/Time Formatting Utilities
 * 
 * Provides consistent date and time formatting across the application.
 * 
 * Date format: MM.DD.YYYY (e.g., 11.26.2021)
 * Time format: HH:MM (24-hour, no seconds, no AM/PM) (e.g., 14:35)
 * DateTime format: MM.DD.YYYY HH:MM (e.g., 11.26.2021 14:35)
 */

const EMPTY_VALUE = '—';

/**
 * Pads a number with leading zeros to ensure 2 digits
 */
const padZero = (num: number): string => {
    return num.toString().padStart(2, '0');
};

/**
 * Validates if a value is a valid Date object
 */
const isValidDate = (date: unknown): date is Date => {
    return date instanceof Date && !isNaN(date.getTime());
};

/**
 * Parses a value into a Date object
 * Returns null if the value cannot be parsed into a valid date
 */
const parseDate = (value: unknown): Date | null => {
    if (value === null || value === undefined || value === '') {
        return null;
    }

    if (value instanceof Date) {
        return isValidDate(value) ? value : null;
    }

    if (typeof value === 'string' || typeof value === 'number') {
        const date = new Date(value);
        return isValidDate(date) ? date : null;
    }

    return null;
};

/**
 * Formats a date as DD.MM.YYYY
 * 
 * @param value - Date object, date string, or timestamp
 * @returns Formatted date string or dash for invalid/missing values
 * 
 * @example
 * formatDate(new Date('2021-11-26')) // "11.26.2021"
 * formatDate('2021-03-05T10:30:00') // "03.05.2021"
 * formatDate(null) // "—"
 */
export const formatDate = (value: unknown): string => {
    const date = parseDate(value);
    
    if (!date) {
        return EMPTY_VALUE;
    }

    const day = padZero(date.getDate());
    const month = padZero(date.getMonth() + 1);
    const year = date.getFullYear();

    return `${day}.${month}.${year}`;
};

/**
 * Formats a time as HH:MM (24-hour format, no seconds)
 * 
 * @param value - Date object, date string, or timestamp
 * @returns Formatted time string or dash for invalid/missing values
 * 
 * @example
 * formatTime(new Date('2021-11-26T14:35:22')) // "14:35"
 * formatTime('2021-11-26T08:05:00') // "08:05"
 * formatTime(null) // "—"
 */
export const formatTime = (value: unknown): string => {
    const date = parseDate(value);
    
    if (!date) {
        return EMPTY_VALUE;
    }

    const hours = padZero(date.getHours());
    const minutes = padZero(date.getMinutes());

    return `${hours}:${minutes}`;
};

/**
 * Formats a date and time as MM.DD.YYYY HH:MM
 * 
 * @param value - Date object, date string, or timestamp
 * @returns Formatted datetime string or dash for invalid/missing values
 * 
 * @example
 * formatDateTime(new Date('2021-11-26T14:35:22')) // "11.26.2021 14:35"
 * formatDateTime('2021-03-05T08:05:00') // "03.05.2021 08:05"
 * formatDateTime(null) // "—"
 */
export const formatDateTime = (value: unknown): string => {
    const date = parseDate(value);
    
    if (!date) {
        return EMPTY_VALUE;
    }

    return `${formatDate(date)} ${formatTime(date)}`;
};

/**
 * Formats a date for display, handling various input types
 * This is a convenience wrapper that accepts the cellType to determine format
 * 
 * @param value - The value to format
 * @param type - The type of formatting: 'date', 'time', or 'datetime'
 * @returns Formatted string
 */
export const formatDateTimeValue = (
    value: unknown,
    type: 'date' | 'time' | 'datetime'
): string => {
    switch (type) {
        case 'date':
            return formatDate(value);
        case 'time':
            return formatTime(value);
        case 'datetime':
            return formatDateTime(value);
        default:
            return EMPTY_VALUE;
    }
};

/**
 * Empty value constant for consistent display of missing values
 */
export { EMPTY_VALUE };
