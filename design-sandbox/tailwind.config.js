/** @type {import('tailwindcss').Config} */
export default {
    content: [
        "./index.html",
        "./src/**/*.{js,ts,jsx,tsx}",
    ],
    darkMode: ['selector', '[data-theme="dark"]'],
    theme: {
        extend: {
            colors: {
                // Theme tokens using CSS variables
                bg: 'var(--bg)',
                'bg-secondary': 'var(--bg-secondary)',
                surface: 'var(--surface)',
                'surface-2': 'var(--surface-2)',
                'surface-3': 'var(--surface-3)',
                border: 'var(--border)',
                'border-light': 'var(--border-light)',
                foreground: {
                    DEFAULT: 'var(--text)',
                    secondary: 'var(--text-secondary)',
                    muted: 'var(--text-muted)',
                    inverse: 'var(--text-inverse)',
                },
                
                // Semantic colors
                primary: {
                    DEFAULT: 'var(--primary)',
                    hover: 'var(--primary-hover)',
                    light: 'var(--primary-light)',
                    dark: 'var(--primary-dark)',
                },
                danger: {
                    DEFAULT: 'var(--danger)',
                    hover: 'var(--danger-hover)',
                    light: 'var(--danger-light)',
                },
                warning: {
                    DEFAULT: 'var(--warning)',
                    hover: 'var(--warning-hover)',
                    light: 'var(--warning-light)',
                },
                success: {
                    DEFAULT: 'var(--success)',
                    hover: 'var(--success-hover)',
                    light: 'var(--success-light)',
                },
                info: {
                    DEFAULT: 'var(--info)',
                    hover: 'var(--info-hover)',
                    light: 'var(--info-light)',
                },
                
                // Table colors
                'table-header': 'var(--table-header)',
                'table-border': 'var(--table-border)',
                'table-row-hover': 'var(--table-row-hover)',
                'table-row-selected': 'var(--table-row-selected)',
                'table-text': 'var(--table-text)',
                'table-text-secondary': 'var(--table-text-secondary)',
                
                // Input & Form colors
                'input-bg': 'var(--input-bg)',
                'input-border': 'var(--input-border)',
                'input-border-focus': 'var(--input-border-focus)',
                'input-text': 'var(--input-text)',
                'input-placeholder': 'var(--input-placeholder)',
                
                // Button colors
                'button-primary-bg': 'var(--button-primary-bg)',
                'button-primary-hover': 'var(--button-primary-hover)',
                'button-primary-text': 'var(--button-primary-text)',
                'button-secondary-bg': 'var(--button-secondary-bg)',
                'button-secondary-hover': 'var(--button-secondary-hover)',
                'button-secondary-text': 'var(--button-secondary-text)',
                
                // Modal colors
                'modal-bg': 'var(--modal-bg)',
                'modal-overlay': 'var(--modal-overlay)',
                'modal-border': 'var(--modal-border)',
                
                // Context menu colors
                'context-menu-bg': 'var(--context-menu-bg)',
                'context-menu-border': 'var(--context-menu-border)',
                'context-menu-hover': 'var(--context-menu-hover)',
                'context-menu-text': 'var(--context-menu-text)',
                'context-menu-text-secondary': 'var(--context-menu-text-secondary)',
                
                // Widget colors
                'widget-bg': 'var(--widget-bg)',
                'widget-border': 'var(--widget-border)',
                'widget-accent-blue': 'var(--widget-accent-blue)',
                'widget-accent-green': 'var(--widget-accent-green)',
                'widget-text-accent': 'var(--widget-text-accent)',
                
                // Editable cell colors
                'editable-cell-bg': 'var(--editable-cell-bg)',
                'editable-cell-border': 'var(--editable-cell-border)',
                'editable-cell-border-error': 'var(--editable-cell-border-error)',
                'editable-cell-hover': 'var(--editable-cell-hover)',
                'editable-cell-text': 'var(--editable-cell-text)',
                
                // Legacy colors (for backward compatibility)
                expense: 'var(--expense)',
                income: 'var(--income)',
            },
            fontFamily: {
                sans: ['Space Grotesk', 'Inter', 'system-ui', 'sans-serif'],
                serif: ['Instrument Serif', 'Cormorant Garamond', 'Georgia', 'serif'],
                mono: ['JetBrains Mono', 'ui-monospace', 'monospace'],
            },
            fontSize: {
                'table-sm': ['13px', '1.4'],
                'table-xs': ['12px', '1.4'],
            },
            boxShadow: {
                'sm': 'var(--shadow-sm)',
                'DEFAULT': 'var(--shadow)',
                'md': 'var(--shadow-md)',
                'lg': 'var(--shadow-lg)',
                'xl': 'var(--shadow-xl)',
            },
            borderRadius: {
                'sm': 'var(--radius-sm)',
                'DEFAULT': 'var(--radius-md)',
                'md': 'var(--radius-md)',
                'lg': 'var(--radius-lg)',
                'xl': 'var(--radius-xl)',
                '2xl': 'var(--radius-2xl)',
                'full': 'var(--radius-full)',
            },
        },
    },
    plugins: [],
}
