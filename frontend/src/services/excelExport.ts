import ExcelJS from 'exceljs';
import { Transaction } from './api';
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

/** Calculate display width of a string (cyrillic chars are ~1.2x wider) */
const calcTextWidth = (text: string): number => {
    let width = 0;
    for (let i = 0; i < text.length; i++) {
        const code = text.charCodeAt(i);
        // Cyrillic range: U+0400–U+04FF
        if (code >= 0x0400 && code <= 0x04FF) {
            width += 1.2;
        } else if (code >= 0x30 && code <= 0x39) {
            // Digits 0-9
            width += 0.9;
        } else if (code === 0x20) {
            // Space
            width += 0.6;
        } else {
            width += 1.0;
        }
    }
    return width;
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

const formatExcelValue = (row: Transaction, columnId: string, rowIndex: number) => {
    const value = (row as any)[columnId];
    const txDate = row.transaction_date ? new Date(row.transaction_date) : null;

    if (columnId === 'row_number') {
        return rowIndex + 1;
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
};

export const exportTransactionsToExcel = async (options: ExportOptions) => {
    const { rows, columns, columnStyles = {}, cellStyles = {}, fileName = 'transactions.xlsx', includeAlternating = false } = options;
    const workbook = new ExcelJS.Workbook();
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
    rows.forEach((row, rowIdx) => {
        const excelRow = sheet.addRow(
            columns.map(col => formatExcelValue(row, col.id, rowIdx))
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

    // --- Auto-fit column widths by actual content ---
    sheet.columns.forEach((col, idx) => {
        const colId = columns[idx]?.id;
        const headerText = String(col.header ?? '');
        let maxWidth = calcTextWidth(headerText);

        // Scan all data values in this column
        const excelCol = sheet.getColumn(idx + 1);
        excelCol.eachCell({ includeEmpty: false }, (cell, rowNumber) => {
            if (rowNumber === 1) return; // skip header, already counted
            const val = cell.value;
            const text = val === null || val === undefined ? '' : String(val);
            const w = calcTextWidth(text);
            if (w > maxWidth) maxWidth = w;
        });

        // For numbers with format (#,##0.00), account for thousand separators
        if (colId === 'amount' || colId === 'balance_after') {
            maxWidth = Math.max(maxWidth, 12); // minimum for formatted numbers
        }

        // Add padding and clamp
        const fitted = Math.min(Math.ceil(maxWidth) + 3, 50);
        col.width = Math.max(fitted, 4);
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
