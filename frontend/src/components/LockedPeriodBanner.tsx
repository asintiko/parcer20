type LockedPeriodBannerProps = {
    message: string;
};

export function LockedPeriodBanner({ message }: LockedPeriodBannerProps) {
    if (!message) return null;
    return (
        <div className="mb-3 rounded-md border border-warning/40 bg-warning-light px-4 py-2 text-sm text-warning">
            {message}
        </div>
    );
}
