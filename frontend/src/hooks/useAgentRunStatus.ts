import type { AgentRun } from '../services/api';

export function useAgentRunStatus(runs: AgentRun[]) {
    const latestRun = runs.length ? runs[0] : null;
    return {
        latestRun,
        isRunning: latestRun?.status === 'queued' || latestRun?.status === 'processing',
        isAwaitingConfirmation: latestRun?.status === 'awaiting_confirmation',
        isCompleted: latestRun?.status === 'completed',
        hasFailed: latestRun?.status === 'failed',
    };
}
