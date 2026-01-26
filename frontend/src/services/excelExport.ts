import ExcelJS from 'exceljs';
import { Transaction } from './api';

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

const pxToExcelWidth = (px?: number) => {
    if (!px) return 14;
    return Math.max(12, Math.round(px / 7));
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

const getAlignment = (align?: Alignment) => {
    if (!align) return undefined;
    return { horizontal: align as any };
};

const formatExcelValue = (row: Transaction, columnId: string, rowIndex: number) => {
    const value = (row as any)[columnId];
    const txDate = row.transaction_date ? new Date(row.transaction_date) : null;

    if (columnId === 'row_number') {
        return rowIndex + 1;
    }
    if (columnId === 'date_time') return txDate || '';
    if (columnId === 'transaction_date') return txDate || '';
    if (columnId === 'time') return txDate || '';
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
        properties: { defaultRowHeight: 18 },
        pageSetup: { fitToPage: true },
    });

    sheet.columns = columns.map(col => ({
        header: col.header,
        key: col.id,
        width: pxToExcelWidth(col.widthPx),
    }));

    // Freeze header row and enable autofilter
    sheet.views = [{ state: 'frozen', ySplit: 1 }];
    sheet.autoFilter = {
        from: { row: 1, column: 1 },
        to: { row: 1, column: columns.length },
    };

    const headerRow = sheet.getRow(1);
    headerRow.font = { bold: true, color: { argb: 'FF0F172A' } };
    headerRow.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: HEADER_FILL } };
    headerRow.alignment = { vertical: 'middle' };
    headerRow.height = 22;
    headerRow.eachCell((cell) => {
        cell.border = { top: BORDER_SIDE, left: BORDER_SIDE, bottom: BORDER_SIDE, right: BORDER_SIDE } as ExcelJS.Borders;
    });

    rows.forEach((row, rowIdx) => {
        const excelRow = sheet.addRow(
            columns.map(col => formatExcelValue(row, col.id, rowIdx))
        );
        const isEven = rowIdx % 2 === 1;
        columns.forEach((col, colIdx) => {
            const excelCell = excelRow.getCell(colIdx + 1);
            const colStyle = columnStyles[col.id] || {};
            const cellKey = `${row.id}:${col.id}`;
            const cellStyle = cellStyles[cellKey] || {};

            const bg = colorToARGB(cellStyle.backgroundColor || colStyle.backgroundColor);
            if (bg) {
                excelCell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: bg } };
            } else if (includeAlternating && isEven) {
                excelCell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFF8FAFC' } }; // slate-50
            }

            const alignment = getAlignment(cellStyle.textAlign || colStyle.textAlign) || { horizontal: 'left' as const };
            excelCell.alignment = alignment;

            const numFmt = getNumberFormat(col.id);
            if (numFmt) {
                excelCell.numFmt = numFmt;
            }

            excelCell.border = { top: BORDER_SIDE, left: BORDER_SIDE, bottom: BORDER_SIDE, right: BORDER_SIDE } as ExcelJS.Borders;

            if (colStyle.fontWeight === 'bold' || cellStyle.fontWeight === 'bold') {
                excelCell.font = { ...(excelCell.font || {}), bold: true };
            }
        });
    });

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
