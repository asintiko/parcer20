/**
 * MUI Autocomplete component for operator/app selection with freeSolo mode
 */
import Autocomplete from '@mui/material/Autocomplete';
import TextField from '@mui/material/TextField';
import { styled } from '@mui/material/styles';

interface AutocompleteInputProps {
    value: string;
    onChange: (value: string) => void;
    options: string[];
    label?: string;
    placeholder?: string;
    required?: boolean;
    disabled?: boolean;
    zIndex?: number;
}

// Custom styled Autocomplete for dark theme compatibility
const StyledAutocomplete = styled(Autocomplete)(() => ({
    '& .MuiOutlinedInput-root': {
        backgroundColor: 'var(--color-surface)',
        color: 'var(--color-foreground)',
        fontSize: '0.875rem',
        '& fieldset': {
            borderColor: 'var(--color-border)',
        },
        '&:hover fieldset': {
            borderColor: 'var(--color-primary)',
        },
        '&.Mui-focused fieldset': {
            borderColor: 'var(--color-primary)',
        },
    },
    '& .MuiInputBase-input': {
        color: 'var(--color-foreground)',
        padding: '8px 12px !important',
    },
    '& .MuiInputLabel-root': {
        color: 'var(--color-foreground-secondary)',
        '&.Mui-focused': {
            color: 'var(--color-primary)',
        },
    },
    '& .MuiAutocomplete-clearIndicator': {
        color: 'var(--color-foreground-secondary)',
    },
    '& .MuiAutocomplete-popupIndicator': {
        color: 'var(--color-foreground-secondary)',
    },
}));

export const AutocompleteInput: React.FC<AutocompleteInputProps> = ({
    value,
    onChange,
    options,
    label,
    placeholder,
    required,
    disabled,
    zIndex = 1500,
}) => {
    return (
        <StyledAutocomplete
            freeSolo
            options={options}
            value={value}
            onChange={(_, newValue) => {
                const nextVal = typeof newValue === 'string' ? newValue : (newValue as string | null);
                onChange(nextVal || '');
            }}
            onInputChange={(_, newInputValue) => {
                onChange(newInputValue);
            }}
            disabled={disabled}
            size="small"
            renderInput={(params) => (
                <TextField
                    {...params}
                    label={label}
                    placeholder={placeholder}
                    required={required}
                    variant="outlined"
                    size="small"
                />
            )}
            slotProps={{
                popper: {
                    sx: {
                        zIndex: zIndex,
                    },
                },
                paper: {
                    sx: {
                        backgroundColor: 'var(--color-surface)',
                        color: 'var(--color-foreground)',
                        border: '1px solid var(--color-border)',
                        boxShadow: '0 8px 32px rgba(0,0,0,0.3)',
                        '& .MuiAutocomplete-option': {
                            color: 'var(--color-foreground)',
                            fontSize: '0.875rem',
                            '&:hover': {
                                backgroundColor: 'var(--color-surface-2)',
                            },
                            '&[aria-selected="true"]': {
                                backgroundColor: 'var(--color-primary)',
                                color: 'white',
                                '&:hover': {
                                    backgroundColor: 'var(--color-primary)',
                                },
                            },
                            '&.Mui-focused': {
                                backgroundColor: 'var(--color-surface-2)',
                            },
                        },
                        '& .MuiAutocomplete-noOptions': {
                            color: 'var(--color-foreground-secondary)',
                            fontSize: '0.875rem',
                        },
                    },
                },
            }}
            noOptionsText="Нет совпадений (введите вручную)"
        />
    );
};
