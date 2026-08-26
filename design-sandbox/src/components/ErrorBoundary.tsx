import React from 'react';

type ErrorBoundaryProps = {
    children: React.ReactNode;
    title?: string;
    description?: string;
    onRetry?: () => void;
};

type ErrorBoundaryState = {
    hasError: boolean;
};

export class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
    constructor(props: ErrorBoundaryProps) {
        super(props);
        this.state = { hasError: false };
    }

    static getDerivedStateFromError(): ErrorBoundaryState {
        return { hasError: true };
    }

    componentDidCatch(error: Error, info: React.ErrorInfo): void {
        // Keep logs visible for desktop troubleshooting.
        // eslint-disable-next-line no-console
        console.error('ErrorBoundary caught:', error, info);
    }

    private handleRetry = () => {
        this.setState({ hasError: false });
        this.props.onRetry?.();
    };

    render() {
        if (this.state.hasError) {
            return (
                <div className="p-4 rounded-lg border border-danger/40 bg-danger/10 text-danger">
                    <div className="text-sm font-semibold">{this.props.title || 'Ошибка интерфейса'}</div>
                    <div className="text-xs mt-1 text-danger/80">
                        {this.props.description || 'Раздел временно недоступен. Нажмите «Повторить». '}
                    </div>
                    <button
                        type="button"
                        className="mt-3 px-3 py-1.5 text-xs rounded border border-danger/50 hover:bg-danger/20"
                        onClick={this.handleRetry}
                    >
                        Повторить
                    </button>
                </div>
            );
        }

        return this.props.children;
    }
}

