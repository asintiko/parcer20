import type ExcelJS from 'exceljs';
import { AccessScope, Transaction, securityApi } from './api';
import { formatDate, formatTime, formatDateTime } from '../utils/dateTimeFormatters';

type Alignment = 'left' | 'center' | 'right';

export type ExportColumn = {
    id: string;
    header: string;
    widthPx?: number;
    textAlign?: Alignment;
};

type StyleMap = Record<string, { backgroundColor?: string; textAlign?: Alignment; fontWeight?: string }>;

const HEADER_FILL = 'FFE5E7EB'; // gray-200
const BORDER_SIDE = { style: 'thin', color: { argb: 'FFCBD5E1' } } as const; // slate-300
const DATA_FONT_SIZE = 10;
const HEADER_FONT_SIZE = 10;

/** Alignment mapping by column ID (not position — safe with reorder/hide) */
const COLUMN_ALIGNMENT: Record<string, Alignment> = {
    row_number: 'center',
    operation_number: 'center',
    date_time: 'center',
    transaction_date: 'center',
    time: 'center',
    day: 'center',
    operator_raw: 'left',
    application_mapped: 'center',
    receiver_name: 'left',
    receiver_card: 'center',
    amount: 'right',
    balance_after: 'right',
    card_last_4: 'center',
    is_p2p: 'center',
    transaction_type: 'center',
    currency: 'center',
    source_type: 'center',
    parsing_method: 'center',
    parsing_confidence: 'center',
};

/**
 * Fixed widths for columns with known, constant-format data.
 * Values are in Excel character units (≈ number of characters in Calibri 11pt).
 */
const FIXED_WIDTHS: Record<string, number> = {
    row_number: 5,           // "№" → "9999"
    operation_number: 9,     // "№ опер." → "999999"
    date_time: 17,           // "Дата и Время" → "30.01.2026 11:40"
    transaction_date: 11,    // "Дата" → "30.01.2026"
    time: 6,                 // "Время" → "11:40"
    day: 5,                  // "День" → "пт"
    card_last_4: 5,          // "ПК" → "1234"
    is_p2p: 4,               // "П2П" → "1"
    transaction_type: 11,    // "Тип" → "Пополнение"
    currency: 7,             // "Валюта" → "UZS"
    source_type: 9,          // "Источник" → "Телеграм"
    parsing_method: 6,       // → "Regex"
    parsing_confidence: 9,   // → "100%"
};

const colorToARGB = (color?: string) => {
    if (!color || color === 'transparent') return undefined;
    const hex = color.trim();
    if (hex.startsWith('#')) {
        const clean = hex.replace('#', '');
        const full = clean.length === 3
            ? clean.split('').map(c => c + c).join('')
            : clean.padEnd(6, '0');
        return `FF${full.toUpperCase()}`;
    }
    const rgbaMatch = hex.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([0-9.]+))?\)/i);
    if (rgbaMatch) {
        const r = parseInt(rgbaMatch[1], 10);
        const g = parseInt(rgbaMatch[2], 10);
        const b = parseInt(rgbaMatch[3], 10);
        const a = rgbaMatch[4] !== undefined ? Math.round(parseFloat(rgbaMatch[4]) * 255) : 255;
        const toHex = (v: number) => v.toString(16).padStart(2, '0').toUpperCase();
        return `${toHex(a)}${toHex(r)}${toHex(g)}${toHex(b)}`;
    }
    return undefined;
};

const formatExcelValue = (
    row: Transaction,
    columnId: string,
    rowIndex: number,
    totalRows: number,
    operationNumberDescending: boolean,
) => {
    const value = (row as any)[columnId];
    const txDate = row.transaction_date ? new Date(row.transaction_date) : null;

    if (columnId === 'row_number') {
        return rowIndex + 1;
    }
    if (columnId === 'operation_number') {
        return operationNumberDescending ? Math.max(totalRows - rowIndex, 0) : rowIndex + 1;
    }
    if (columnId === 'date_time') return txDate ? formatDateTime(txDate) : '';
    if (columnId === 'transaction_date') return txDate ? formatDate(txDate) : '';
    if (columnId === 'time') return txDate ? formatTime(txDate) : '';
    if (columnId === 'day') {
        const days = ['вс', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб'];
        return txDate ? days[txDate.getDay()] : '';
    }
    if (columnId === 'amount' || columnId === 'balance_after') {
        const num = value !== undefined && value !== null ? parseFloat(String(value)) : NaN;
        return Number.isNaN(num) ? '' : Math.abs(num);
    }
    if (columnId === 'parsing_confidence') {
        if (value === null || value === undefined) return '';
        return `${Math.round(Number(value) * 100)}%`;
    }
    if (columnId === 'is_p2p') return value ? 1 : '';
    if (columnId === 'transaction_type') {
        const map: Record<string, string> = {
            DEBIT: 'Списание',
            CREDIT: 'Пополнение',
            CONVERSION: 'Конверсия',
            REVERSAL: 'Отмена',
        };
        return row.transaction_type_display || map[String(value)] || String(value ?? '');
    }
    if (columnId === 'source_type') {
        const sourceLabels: Record<string, string> = {
            TELEGRAM: 'Телеграм',
            SMS: 'СМС',
            MANUAL: 'Ручной',
        };
        return row.source_display || sourceLabels[row.source_channel as string] || '';
    }
    if (columnId === 'parsing_method') {
        if (!value) return '';
        if (String(value).startsWith('REGEX')) return 'Regex';
        return String(value);
    }
    if (columnId === 'receiver_name') return value ?? '';
    if (columnId === 'receiver_card') return value ?? '';
    return value ?? '';
};

const isTransactionWithinScope = (row: Transaction, scope?: AccessScope | null): boolean => {
    if (!scope) return true;
    const txDate = row.transaction_date ? new Date(row.transaction_date) : null;
    if (!txDate || Number.isNaN(txDate.getTime())) return false;

    const scopeYears = scope.years || [];
    if (scopeYears.length && !scopeYears.includes(txDate.getFullYear())) {
        return false;
    }

    if (scope.period_start) {
        const from = new Date(scope.period_start);
        if (!Number.isNaN(from.getTime()) && txDate < from) {
            return false;
        }
    }
    if (scope.period_end) {
        const to = new Date(scope.period_end);
        if (!Number.isNaN(to.getTime()) && txDate > to) {
            return false;
        }
    }
    return true;
};

const getNumberFormat = (columnId: string) => {
    if (columnId === 'amount' || columnId === 'balance_after') return '#,##0.00';
    if (columnId === 'date_time') return 'yyyy.mm.dd hh:mm';
    if (columnId === 'transaction_date') return 'yyyy.mm.dd';
    if (columnId === 'time') return 'hh:mm';
    return undefined;
};

type ExportOptions = {
    rows: Transaction[];
    columns: ExportColumn[];
    columnStyles?: StyleMap;
    cellStyles?: StyleMap;
    fileName?: string;
    includeAlternating?: boolean;
    operationNumberDescending?: boolean;
    operationNumberTotal?: number;
};

export const exportTransactionsToExcel = async (options: ExportOptions) => {
    const {
        rows,
        columns,
        columnStyles = {},
        cellStyles = {},
        fileName = 'transactions.xlsx',
        includeAlternating = false,
        operationNumberDescending = false,
        operationNumberTotal,
    } = options;
    let exportRows = rows;
    try {
        const [lockResponse, scopeStatus] = await Promise.all([
            securityApi.getLockedPeriods(),
            securityApi.getStatus(),
        ]);
        const periods = lockResponse?.periods || [];
        const currentScope = scopeStatus?.current_scope || null;

        exportRows = rows.filter((row) => isTransactionWithinScope(row, currentScope));

        if (periods.length) {
            exportRows = exportRows.filter((row) => {
                const txDate = row.transaction_date ? new Date(row.transaction_date) : null;
                if (!txDate || Number.isNaN(txDate.getTime())) return true;
                const txDateOnly = new Date(txDate.getFullYear(), txDate.getMonth(), txDate.getDate()).getTime();
                return !periods.some((period) => {
                    const from = new Date(period.date_from);
                    const to = new Date(period.date_to);
                    if (Number.isNaN(from.getTime()) || Number.isNaN(to.getTime())) return false;
                    const fromOnly = new Date(from.getFullYear(), from.getMonth(), from.getDate()).getTime();
                    const toOnly = new Date(to.getFullYear(), to.getMonth(), to.getDate()).getTime();
                    return txDateOnly >= fromOnly && txDateOnly <= toOnly;
                });
            });
        }
    } catch {
        // Export should still work if lock metadata endpoint is temporarily unavailable.
    }

    // Pulled in on demand so the ~900KB exceljs bundle never lands in the
    // startup chunk — only when a user actually triggers an export.
    const { default: ExcelJSModule } = await import('exceljs');
    const workbook = new ExcelJSModule.Workbook();
    const sheet = workbook.addWorksheet('Транзакции', {
        properties: { defaultRowHeight: 15 },
        pageSetup: { fitToPage: true },
    });

    // Initial columns — width will be auto-fitted later
    sheet.columns = columns.map(col => ({
        header: col.header,
        key: col.id,
        width: 10, // placeholder, auto-fit below
    }));

    // Freeze header row and enable autofilter
    sheet.views = [{ state: 'frozen', ySplit: 1 }];
    sheet.autoFilter = {
        from: { row: 1, column: 1 },
        to: { row: 1, column: columns.length },
    };

    // --- Header row ---
    const headerRow = sheet.getRow(1);
    headerRow.font = { bold: true, size: HEADER_FONT_SIZE, color: { argb: 'FF0F172A' } };
    headerRow.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: HEADER_FILL } };
    headerRow.alignment = { vertical: 'middle', wrapText: false };
    headerRow.height = 18;
    headerRow.eachCell((cell, colNumber) => {
        cell.border = { top: BORDER_SIDE, left: BORDER_SIDE, bottom: BORDER_SIDE, right: BORDER_SIDE } as ExcelJS.Borders;
        const colId = columns[colNumber - 1]?.id;
        const desired = colId ? COLUMN_ALIGNMENT[colId] : undefined;
        cell.alignment = { vertical: 'middle', horizontal: desired || 'center', wrapText: false };
    });

    // --- Data rows ---
    exportRows.forEach((row, rowIdx) => {
        const excelRow = sheet.addRow(
            columns.map(col => formatExcelValue(
                row,
                col.id,
                rowIdx,
                operationNumberTotal ?? exportRows.length,
                operationNumberDescending,
            ))
        );
        excelRow.height = 15;
        const isEven = rowIdx % 2 === 1;

        columns.forEach((col, colIdx) => {
            const excelCell = excelRow.getCell(colIdx + 1);
            const colStyle = columnStyles[col.id] || {};
            const cellKey = `${row.id}:${col.id}`;
            const cellStyle = cellStyles[cellKey] || {};

            // Font
            const isBold = colStyle.fontWeight === 'bold' || cellStyle.fontWeight === 'bold';
            excelCell.font = { size: DATA_FONT_SIZE, ...(isBold ? { bold: true } : {}) };

            // Background
            const bg = colorToARGB(cellStyle.backgroundColor || colStyle.backgroundColor);
            if (bg) {
                excelCell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: bg } };
            } else if (includeAlternating && isEven) {
                excelCell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFF8FAFC' } };
            }

            // Alignment — by column ID, single-line
            const desired = COLUMN_ALIGNMENT[col.id] || 'left';
            excelCell.alignment = { horizontal: desired, vertical: 'middle', wrapText: false };

            // Number format
            const numFmt = getNumberFormat(col.id);
            if (numFmt) {
                excelCell.numFmt = numFmt;
            }

            // Border
            excelCell.border = { top: BORDER_SIDE, left: BORDER_SIDE, bottom: BORDER_SIDE, right: BORDER_SIDE } as ExcelJS.Borders;
        });
    });

    // --- Auto-fit column widths ---
    sheet.columns.forEach((col, idx) => {
        const colId = columns[idx]?.id;

        // Fixed widths for columns with known constant format
        const fixed = colId ? FIXED_WIDTHS[colId] : undefined;
        if (fixed) {
            col.width = fixed;
            return;
        }

        // Dynamic columns: measure by string length
        const headerLen = String(col.header ?? '').length;
        let maxLen = headerLen;
        const isNumericCol = colId === 'amount' || colId === 'balance_after';

        const excelCol = sheet.getColumn(idx + 1);
        excelCol.eachCell({ includeEmpty: false }, (cell, rowNumber) => {
            if (rowNumber === 1) return;
            const val = cell.value;
            let len: number;

            if (isNumericCol && typeof val === 'number') {
                // Formatted number with separators: "1 234 567,89"
                len = new Intl.NumberFormat('ru-RU', {
                    minimumFractionDigits: 2,
                    maximumFractionDigits: 2,
                }).format(Math.abs(val)).length;
            } else {
                len = val === null || val === undefined ? 0 : String(val).length;
            }

            if (len > maxLen) maxLen = len;
        });

        // +1 char padding, clamp to max 40, and enforce sane minimum
        // width for numeric columns to avoid Excel "###" rendering.
        const computed = Math.min(maxLen + 1, 40);
        col.width = isNumericCol ? Math.max(computed, 14) : Math.max(computed, 8);
    });

    // --- Write & download ---
    const buffer = await workbook.xlsx.writeBuffer();
    const blob = new Blob([buffer], {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    });
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = fileName;
    link.click();
    window.URL.revokeObjectURL(url);
};
