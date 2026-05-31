import { createTheme } from '@mui/material/styles';

export const muiTheme = createTheme({
    zIndex: {
        appBar: 10,
        drawer: 30,
        modal: 40,
        snackbar: 60,
        tooltip: 70,
    },
    components: {
        MuiCssBaseline: {
            styleOverrides: {
                'html, body, #root': {
                    backgroundColor: 'var(--bg) !important',
                    color: 'var(--text) !important',
                },
                'input, textarea, select': {
                    color: 'var(--input-text) !important',
                    WebkitTextFillColor: 'var(--input-text)',
                    backgroundColor: 'var(--input-bg)',
                    borderColor: 'var(--input-border)',
                },
                'select option, select optgroup': {
                    color: 'var(--text) !important',
                    backgroundColor: 'var(--surface) !important',
                },
                '.MuiInputBase-input, .MuiOutlinedInput-input, .MuiSelect-select': {
                    color: 'var(--text) !important',
                    WebkitTextFillColor: 'var(--text)',
                },
                '.MuiMenu-paper, .MuiPopover-paper, .MuiMenu-list': {
                    backgroundColor: 'var(--surface) !important',
                    color: 'var(--text) !important',
                },
                '.MuiMenuItem-root': {
                    color: 'var(--text) !important',
                    backgroundColor: 'var(--surface) !important',
                },
                '.MuiAutocomplete-popper': {
                    zIndex: 'var(--z-popper)',
                },
                '.MuiPickersPopper-root': {
                    zIndex: 'var(--z-popper)',
                },
                /* Date picker / calendar — visible in dark via tokens */
                '.MuiPickersPopper-paper, .MuiDateCalendar-root, .MuiPickersLayout-root, .MuiPickersLayout-contentWrapper': {
                    backgroundColor: 'var(--surface) !important',
                    color: 'var(--text) !important',
                    borderColor: 'var(--border) !important',
                },
                '.MuiPickersDay-root': {
                    color: 'var(--text) !important',
                    backgroundColor: 'transparent !important',
                },
                '.MuiPickersDay-root.Mui-disabled': {
                    color: 'var(--text-muted) !important',
                },
                '.MuiPickersDay-root:not(.Mui-selected):hover': {
                    backgroundColor: 'var(--surface-2) !important',
                },
                '.MuiPickersDay-root.Mui-selected, .MuiPickersDay-root.Mui-selected:hover, .MuiPickersDay-root.Mui-selected:focus': {
                    backgroundColor: 'var(--text) !important',
                    color: 'var(--text-inverse, #fff) !important',
                },
                '.MuiPickersCalendarHeader-label, .MuiPickersCalendarHeader-switchViewButton, .MuiPickersArrowSwitcher-button': {
                    color: 'var(--text) !important',
                },
                '.MuiDayCalendar-weekDayLabel': {
                    color: 'var(--text-muted) !important',
                },
                '.MuiYearCalendar-root .MuiPickersYear-yearButton, .MuiMonthCalendar-root .MuiPickersMonth-monthButton': {
                    color: 'var(--text) !important',
                },
                '.MuiYearCalendar-root .MuiPickersYear-yearButton.Mui-selected, .MuiMonthCalendar-root .MuiPickersMonth-monthButton.Mui-selected': {
                    backgroundColor: 'var(--text) !important',
                    color: 'var(--text-inverse, #fff) !important',
                },
                /* Tooltips */
                '.MuiTooltip-tooltip': {
                    backgroundColor: 'var(--surface-3) !important',
                    color: 'var(--text) !important',
                    border: '1px solid var(--border)',
                    fontFamily: 'var(--font-mono, monospace) !important',
                    fontSize: '11px !important',
                    letterSpacing: '0.04em',
                },
                '.MuiTooltip-arrow': {
                    color: 'var(--surface-3) !important',
                },
            },
        },
        MuiAutocomplete: {
            styleOverrides: {
                paper: {
                    backgroundColor: 'var(--surface)',
                    color: 'var(--text)',
                    border: '1px solid var(--border)',
                    boxShadow: '0 8px 32px rgba(0, 0, 0, 0.4)',
                },
                option: {
                    '&[aria-selected="true"]': {
                        backgroundColor: 'var(--primary)',
                        color: '#fff',
                    },
                    '&.Mui-focused': {
                        backgroundColor: 'var(--surface-2)',
                    },
                },
            },
        },
    },
});
