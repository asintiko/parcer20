/**
 * MUI Autocomplete multi-select for operator_raw selection with freeSolo mode.
 * Selected operators render as chips; supports searching existing operators
 * and entering ones not present in the list.
 */
import Autocomplete from '@mui/material/Autocomplete';
import TextField from '@mui/material/TextField';
import Chip from '@mui/material/Chip';
import { styled } from '@mui/material/styles';

interface MultiOperatorSelectProps {
    value: string[];
    onChange: (value: string[]) => void;
    options: string[];
    placeholder?: string;
    disabled?: boolean;
    zIndex?: number;
}

const StyledAutocomplete = styled(Autocomplete<string, true, false, true>)(() => ({
    '& .MuiOutlinedInput-root': {
        backgroundColor: 'var(--color-surface)',
        color: 'var(--color-foreground)',
        fontSize: '0.875rem',
        borderRadius: '4px',
        padding: '4px 8px',
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
    },
    '& .MuiAutocomplete-clearIndicator': {
        color: 'var(--color-foreground-secondary)',
    },
    '& .MuiAutocomplete-popupIndicator': {
        color: 'var(--color-foreground-secondary)',
    },
    '& .MuiChip-root': {
        backgroundColor: 'var(--color-surface-2)',
        color: 'var(--color-foreground)',
        border: '1px solid var(--color-border)',
        borderRadius: '4px',
        height: '24px',
        fontSize: '0.8125rem',
        '& .MuiChip-deleteIcon': {
            color: 'var(--color-foreground-secondary)',
            '&:hover': {
                color: 'var(--color-foreground)',
            },
        },
    },
}));

export const MultiOperatorSelect: React.FC<MultiOperatorSelectProps> = ({
    value,
    onChange,
    options,
    placeholder,
    disabled,
    zIndex = 1500,
}) => {
    return (
        <StyledAutocomplete
            multiple
            freeSolo
            disableCloseOnSelect
            options={options}
            value={value}
            onChange={(_, newValue) => {
                const cleaned = (newValue as string[])
                    .map((v) => v.trim())
                    .filter(Boolean);
                onChange(Array.from(new Set(cleaned)));
            }}
            disabled={disabled}
            size="small"
            renderTags={(tagValue, getTagProps) =>
                tagValue.map((option, index) => {
                    const { key, ...chipProps } = getTagProps({ index });
                    return <Chip key={key} label={option} {...chipProps} size="small" />;
                })
            }
            renderInput={(params) => (
                <TextField
                    {...params}
                    placeholder={value.length === 0 ? placeholder : undefined}
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
