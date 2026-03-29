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
