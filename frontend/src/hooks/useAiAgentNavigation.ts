import { useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import type { AgentLocateResult } from '../services/api';

export function useAiAgentNavigation() {
    const navigate = useNavigate();

    return useCallback((target?: AgentLocateResult | null) => {
        if (!target || !target.exists) return;
        const route = target.route || '/';
        navigate(route, {
            state: {
                agentNavigation: target,
                ts: Date.now(),
            },
        });
    }, [navigate]);
}
