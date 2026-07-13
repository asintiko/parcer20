import { Lock } from 'lucide-react';

type LockedPeriodBannerProps = {
    message: string;
};

export function LockedPeriodBanner({ message }: LockedPeriodBannerProps) {
    if (!message) return null;
    return (
        <div className="tx-banner is-warn">
            <Lock size={16} className="tx-banner-icon" />
            <div className="tx-banner-body">
                <div className="tx-banner-title">Заблокированный период</div>
                <div className="tx-banner-desc">{message}</div>
            </div>
        </div>
    );
}
