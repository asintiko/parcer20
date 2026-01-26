/**
 * Hook to track background automation status across pages
 */
import { useQuery } from '@tanstack/react-query';
import { automationApi } from '../services/api';

export function useAutomationStatus() {
    // Get active task ID from localStorage
    const activeTaskId = localStorage.getItem('automation_task_id');

    // Poll task status if there's an active task
    const { data: taskStatus } = useQuery({
        queryKey: ['backgroundAutomation', activeTaskId],
        queryFn: () => automationApi.getAnalyzeStatus(activeTaskId!),
        enabled: !!activeTaskId,
        refetchInterval: (query) => {
            if (!query.state.data) return false;
            const status = query.state.data.status;
            // Poll every 3 seconds if processing, stop otherwise
            return status === 'processing' || status === 'started' ? 3000 : false;
        },
        // Clean up if task not found
        retry: (failureCount, error: any) => {
            if (error?.response?.status === 404) {
                localStorage.removeItem('automation_task_id');
                return false;
            }
            return failureCount < 2;
        },
    });

    const isRunning = taskStatus?.status === 'processing' || taskStatus?.status === 'started';
    const isCompleted = taskStatus?.status === 'completed';

    return {
        activeTaskId,
        taskStatus,
        isRunning,
        isCompleted,
        progress: taskStatus?.progress,
    };
}
