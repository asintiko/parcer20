import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { agentApi } from '../services/api';

export function useAiAgentNotifications() {
    const queryClient = useQueryClient();

    const notificationsQuery = useQuery({
        queryKey: ['agent-notifications'],
        queryFn: () => agentApi.listNotifications({ limit: 100 }),
        refetchInterval: 15_000,
        staleTime: 5_000,
    });

    const reportsQuery = useQuery({
        queryKey: ['agent-reports'],
        queryFn: () => agentApi.listReports({ include_team: true, limit: 50 }),
        refetchInterval: 30_000,
        staleTime: 10_000,
    });

    const invalidateAll = async () => {
        await Promise.all([
            queryClient.invalidateQueries({ queryKey: ['agent-notifications'] }),
            queryClient.invalidateQueries({ queryKey: ['agent-reports'] }),
        ]);
    };

    const readMutation = useMutation({
        mutationFn: (notificationId: string) => agentApi.readNotification(notificationId),
        onSuccess: () => void invalidateAll(),
    });

    const readAllMutation = useMutation({
        mutationFn: () => agentApi.readAllNotifications(),
        onSuccess: () => void invalidateAll(),
    });

    const claimMutation = useMutation({
        mutationFn: (itemId: string) => agentApi.claimReportItem(itemId),
        onSuccess: () => void invalidateAll(),
    });

    const releaseMutation = useMutation({
        mutationFn: (itemId: string) => agentApi.releaseReportItem(itemId),
        onSuccess: () => void invalidateAll(),
    });

    return {
        notificationsQuery,
        reportsQuery,
        readMutation,
        readAllMutation,
        claimMutation,
        releaseMutation,
        notifications: notificationsQuery.data || [],
        reports: reportsQuery.data || [],
        unreadCount: (notificationsQuery.data || []).filter((item) => !item.is_read).length,
    };
}
