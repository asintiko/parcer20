/**
 * MUI DateTimePicker components with Russian localization
 */
import { LocalizationProvider } from '@mui/x-date-pickers/LocalizationProvider';
import { AdapterDayjs } from '@mui/x-date-pickers/AdapterDayjs';
import { DateTimePicker as MuiDateTimePicker } from '@mui/x-date-pickers/DateTimePicker';
import { DatePicker as MuiDatePicker } from '@mui/x-date-pickers/DatePicker';
import { TimePicker as MuiTimePicker } from '@mui/x-date-pickers/TimePicker';
import dayjs, { Dayjs } from 'dayjs';
import 'dayjs/locale/ru';

// Shared styles for dark theme compatibility
const getSlotProps = (zIndex = 1400) => ({
    textField: {
        size: 'small' as const,
        fullWidth: true,
        sx: {
            '& .MuiOutlinedInput-root': {
                backgroundColor: 'var(--color-surface)',
                color: 'var(--color-foreground)',
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
                fontSize: '0.875rem',
                padding: '8px 12px',
            },
            '& .MuiInputAdornment-root .MuiSvgIcon-root': {
                color: 'var(--color-foreground-secondary)',
            },
        },
    },
    popper: {
        sx: {
            zIndex: zIndex,
            '& .MuiPaper-root': {
                backgroundColor: 'var(--color-surface)',
                color: 'var(--color-foreground)',
                border: '1px solid var(--color-border)',
                boxShadow: '0 8px 32px rgba(0,0,0,0.3)',
            },
            '& .MuiPickersDay-root': {
                color: 'var(--color-foreground)',
                '&:hover': {
                    backgroundColor: 'var(--color-surface-2)',
                },
                '&.Mui-selected': {
                    backgroundColor: 'var(--color-primary)',
                    color: 'white',
                    '&:hover': {
                        backgroundColor: 'var(--color-primary)',
                    },
                },
            },
            '& .MuiPickersCalendarHeader-label': {
                color: 'var(--color-foreground)',
            },
            '& .MuiPickersCalendarHeader-switchViewIcon': {
                color: 'var(--color-foreground-secondary)',
            },
            '& .MuiPickersArrowSwitcher-button': {
                color: 'var(--color-foreground-secondary)',
            },
            '& .MuiDayCalendar-weekDayLabel': {
                color: 'var(--color-foreground-secondary)',
            },
            '& .MuiClock-pin': {
                backgroundColor: 'var(--color-primary)',
            },
            '& .MuiClockPointer-root': {
                backgroundColor: 'var(--color-primary)',
            },
            '& .MuiClockPointer-thumb': {
                backgroundColor: 'var(--color-primary)',
                borderColor: 'var(--color-primary)',
            },
            '& .MuiClockNumber-root': {
                color: 'var(--color-foreground)',
                '&.Mui-selected': {
                    backgroundColor: 'var(--color-primary)',
                    color: 'white',
                },
            },
            '& .MuiPickersToolbar-root': {
                backgroundColor: 'var(--color-surface-2)',
                color: 'var(--color-foreground)',
            },
            '& .MuiTypography-root': {
                color: 'var(--color-foreground)',
            },
            '& .MuiDialogActions-root': {
                backgroundColor: 'var(--color-surface)',
                borderTop: '1px solid var(--color-border)',
            },
            '& .MuiButton-root': {
                color: 'var(--color-primary)',
            },
            '& .MuiMultiSectionDigitalClock-root': {
                backgroundColor: 'var(--color-surface)',
            },
            '& .MuiMultiSectionDigitalClockSection-root': {
                '&:after': {
                    backgroundColor: 'var(--color-border)',
                },
            },
            '& .MuiMultiSectionDigitalClockSection-item': {
                color: 'var(--color-foreground)',
                '&:hover': {
                    backgroundColor: 'var(--color-surface-2)',
                },
                '&.Mui-selected': {
                    backgroundColor: 'var(--color-primary)',
                    color: 'white',
                    '&:hover': {
                        backgroundColor: 'var(--color-primary)',
                    },
                },
            },
        },
    },
});

interface DateTimePickerProps {
    value: string | null;
    onChange: (value: string | null) => void;
    label?: string;
    required?: boolean;
    disabled?: boolean;
    zIndex?: number;
}

interface DatePickerProps {
    value: string | null;
    onChange: (value: string | null) => void;
    label?: string;
    disabled?: boolean;
    zIndex?: number;
}

interface TimePickerProps {
    value: string | null;
    onChange: (value: string | null) => void;
    label?: string;
    disabled?: boolean;
    zIndex?: number;
}

/**
 * DateTime picker for forms (date + time)
 * Input/Output format: ISO string or "YYYY-MM-DDTHH:mm"
 */
export const DateTimePicker: React.FC<DateTimePickerProps> = ({
    value,
    onChange,
    label,
    disabled,
    zIndex = 1400,
}) => {
    const handleChange = (newValue: Dayjs | null) => {
        if (newValue && newValue.isValid()) {
            onChange(newValue.format('YYYY-MM-DDTHH:mm'));
        } else {
            onChange(null);
        }
    };

    const dayjsValue = value ? dayjs(value) : null;

    return (
        <LocalizationProvider dateAdapter={AdapterDayjs} adapterLocale="ru">
            <MuiDateTimePicker
                label={label}
                value={dayjsValue}
                onChange={handleChange}
                disabled={disabled}
                ampm={false}
                format="DD.MM.YYYY HH:mm"
                slotProps={getSlotProps(zIndex)}
            />
        </LocalizationProvider>
    );
};

/**
 * Date picker for filters (date only)
 * Input/Output format: "YYYY-MM-DD"
 */
export const DatePicker: React.FC<DatePickerProps> = ({
    value,
    onChange,
    label,
    disabled,
    zIndex = 1400,
}) => {
    const handleChange = (newValue: Dayjs | null) => {
        if (newValue && newValue.isValid()) {
            onChange(newValue.format('YYYY-MM-DD'));
        } else {
            onChange(null);
        }
    };

    const dayjsValue = value ? dayjs(value) : null;

    return (
        <LocalizationProvider dateAdapter={AdapterDayjs} adapterLocale="ru">
            <MuiDatePicker
                label={label}
                value={dayjsValue}
                onChange={handleChange}
                disabled={disabled}
                format="DD.MM.YYYY"
                slotProps={getSlotProps(zIndex)}
            />
        </LocalizationProvider>
    );
};

/**
 * Time picker for editing cells (time only)
 * Input/Output format: "HH:mm"
 */
export const TimePicker: React.FC<TimePickerProps> = ({
    value,
    onChange,
    label,
    disabled,
    zIndex = 1400,
}) => {
    const handleChange = (newValue: Dayjs | null) => {
        if (newValue && newValue.isValid()) {
            onChange(newValue.format('HH:mm'));
        } else {
            onChange(null);
        }
    };

    // Parse time string into dayjs (use today's date as base)
    const dayjsValue = value ? dayjs(`2000-01-01T${value}`) : null;

    return (
        <LocalizationProvider dateAdapter={AdapterDayjs} adapterLocale="ru">
            <MuiTimePicker
                label={label}
                value={dayjsValue}
                onChange={handleChange}
                disabled={disabled}
                ampm={false}
                format="HH:mm"
                slotProps={getSlotProps(zIndex)}
            />
        </LocalizationProvider>
    );
};
